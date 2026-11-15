"""Local operator gate. It never changes the environment or performs a GET step."""
from __future__ import annotations

from pathlib import Path

from contracts.protocol import strict_json,ProtocolError


FORMAT='metarescue.operator-control.v1'
MODES=('running','paused','stopping')


class OperationalControl:
    def __init__(self,path,*,session_id):
        self.path=Path(path)
        self.session_id=session_id
        self.request=None
        self.completed_steps=0
        self.reserved_step=None
        self.error=None
        self.stopping=False

    def refresh(self):
        try:
            request=strict_json(self.path.read_bytes(),maximum_bytes=4096)
            if (not isinstance(request,dict) or set(request)!={'format','session_id','revision','mode','step_total'} or
                request['format']!=FORMAT or request['session_id']!=self.session_id or
                type(request['revision']) is not int or not 0<=request['revision']<=2**53-1 or
                type(request['step_total']) is not int or not 0<=request['step_total']<=2**53-1 or
                request['mode'] not in MODES):
                raise ValueError('Invalid operator control document')
            if self.request:
                if request['revision']<self.request['revision']:
                    raise ValueError('Operator revision went backwards')
                if request['revision']==self.request['revision'] and request!=self.request:
                    raise ValueError('Operator revision was reused with different content')
                if request['step_total']<self.request['step_total']:
                    raise ValueError('Operator step counter went backwards')
            self.request=request
            self.error=None
            self.stopping=self.stopping or request['mode']=='stopping'
        except (OSError,ValueError,ProtocolError) as error:
            # Missing, malformed or half-written control must not start movement.
            # A requested safe stop remains latched until terminal confirmation.
            self.error=type(error).__name__+': '+str(error)
        return self.snapshot()

    def take(self):
        self.refresh()
        if self.stopping:return 'stop'
        if self.error or self.request is None:return 'wait'
        if self.request['mode']=='running':
            self.completed_steps=self.request['step_total']
            return 'advance'
        if self.request['step_total']>self.completed_steps:
            self.reserved_step=self.completed_steps+1
            return 'advance'
        return 'wait'

    def complete(self):
        if self.reserved_step is not None:
            self.completed_steps=self.reserved_step
            self.reserved_step=None

    def snapshot(self):
        request=self.request or {'mode':'paused','revision':None,'step_total':0}
        return {'session_id':self.session_id,'requested_mode':request['mode'],
                'effective_mode':'stopping' if self.stopping else 'paused' if self.error else request['mode'],
                'revision':request['revision'],'step_total':request['step_total'],
                'completed_steps':self.completed_steps,'inflight_step':self.reserved_step,
                'error':self.error}
