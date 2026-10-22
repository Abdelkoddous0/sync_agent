"""Conditional S3 object operations; no CLI, multipart threads or unbounded retries.

Requires a boto3/botocore version supporting PutObject/DeleteObject IfMatch.
Old SDKs fail closed (parameter validation), never retry unconditionally.
ETags are opaque revision tokens, NOT assumed to be content hashes.
"""
import os
import time


class S3Store:
    def __init__(self, cfg, client=None):
        self.bucket = cfg['s3_bucket']
        self.prefix = cfg.get('s3_prefix','').strip('/') + '/'
        self.timeout = cfg.get('transfer_timeout',120)
        if client is None:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ProfileNotFound
            from authentication import session_kwargs
            try:
                session = boto3.Session(**session_kwargs(cfg))
            except ProfileNotFound:
                raise ValueError(f'AWS profile "{cfg.get("aws_profile")}" was not found. '
                                 'Run SyncAgent.exe --reconfigure to choose a profile.') from None
            client = session.client('s3', config=Config(
                connect_timeout=min(10,self.timeout), read_timeout=min(20,self.timeout),
                retries={'mode':'standard','total_max_attempts':cfg.get('max_retries',3)},
                max_pool_connections=1))
        self.client = client

    def list(self):
        result = {}
        for page in self.client.get_paginator('list_objects_v2').paginate(
                Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get('Contents',[]):
                key = item['Key']
                if key.startswith(self.prefix) and not key.endswith('/'):
                    result[key[len(self.prefix):]] = item['ETag']
        return result

    def download(self, name, target, expected, stop):
        response = self.client.get_object(Bucket=self.bucket, Key=self.prefix+name, IfMatch=expected)
        body = response['Body']
        # Stall limit per block, not for the whole object: a large file on a slow but
        # working connection must not fail on every pass.
        deadline = time.monotonic() + self.timeout
        size = 0
        try:
            while True:
                if stop.is_set():
                    raise InterruptedError('Stopping download')
                block = body.read(1024*1024)
                if time.monotonic() > deadline:
                    raise TimeoutError('Download stalled beyond the transfer timeout')
                if not block:
                    break
                target.write(block)
                size += len(block)
                deadline = time.monotonic() + self.timeout
            if 'ContentLength' in response and size != response['ContentLength']:
                raise IOError('Incomplete S3 response')
        finally:
            body.close()

    def upload(self, name, source, expected):
        position = source.tell()
        source.seek(0, os.SEEK_END)
        length = source.tell()-position
        source.seek(position)
        # Single conditional PutObject; larger objects need a separately designed
        # conditional multipart protocol, not an unsafe upload_file fallback.
        if length > 5 * 1024**3:
            raise ValueError('Object exceeds safe single-PutObject limit (5 GiB)')
        condition = {'IfNoneMatch':'*'} if expected is None else {'IfMatch':expected}
        response = self.client.put_object(Bucket=self.bucket, Key=self.prefix+name,
                                         Body=source, ContentLength=length, **condition)
        return response['ETag']

    def delete(self, name, expected):
        if expected is None:
            raise ValueError('Refusing unconditional deletion')
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix+name, IfMatch=expected)
