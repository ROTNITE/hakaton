"""Explicit-start job registry: never calculate on page GET, metrics GET, or logs GET."""
from __future__ import annotations
import concurrent.futures,threading,uuid,datetime

class RunManager:
    def __init__(self):
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1,thread_name_prefix='metarescue-run')
        self.lock=threading.Lock();self.jobs={}
    def start(self,args,runner):
        uid=uuid.uuid4().hex
        job={'run_id':uid,'status':'QUEUED','error':None,'data':None,
             'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        with self.lock:
            if any(j['status'] in ('QUEUED','RUNNING') for j in self.jobs.values()):
                raise ValueError('Уже выполняется сравнение. Дождитесь завершения текущего запуска.')
            # Retain up to 2 completed results in memory, prevent unbounded growth.
            for old in list(self.jobs):
                if len(self.jobs)<3:break
                if self.jobs[old]['status'] not in ('RUNNING','QUEUED'):del self.jobs[old]
            self.jobs[uid]=job
        def work():
            with self.lock:job['status']='RUNNING'
            try:
                data=runner(*args[:-1],run_id=uid)
                with self.lock:
                    job['data']=data;job['status']='COMPLETED'
            except Exception as exc:
                with self.lock:
                    job['status']='FAILED';job['error']=f'{type(exc).__name__}: {str(exc)[:1200]}'
        self.pool.submit(work)
        return uid
    def status(self,uid):
        with self.lock:
            job=self.jobs.get(uid)
            if job is None:return None
            return {k:v for k,v in job.items() if k!='data'}
    def result(self,uid):
        with self.lock:
            job=self.jobs.get(uid)
            return job['data'] if job and job['status']=='COMPLETED' else None
RUN_MANAGER=RunManager()
