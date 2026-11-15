"""Deterministic, delayed, evidence-carrying agent communications."""
from __future__ import annotations
import hashlib

class MessageBus:
    def __init__(self,seed,loss_rate=0.0,latency=0.35):
        self.seed=seed;self.loss_rate=loss_rate;self.latency=latency;self.messages=[]
    def send(self,t,sender,recipient,kind,payload,schedule, audit=None):
        mid=f'msg_{len(self.messages)+1:07d}'
        token=f'{self.seed}:{mid}:{sender}:{kind}'.encode('utf8')
        value=int.from_bytes(hashlib.sha256(token).digest()[:8],'little')/2**64
        lost=value<self.loss_rate
        arrive=round(t+self.latency,4)
        msg={'message_id':mid,'t':round(t,4),'sender':sender,'recipient':recipient,
             'type':kind,'payload':payload,'delivery_t':arrive,
             'delivery_status':'lost' if lost else 'queued'}
        self.messages.append(msg)
        if audit is not None:audit(t,'message_bus','MESSAGE_SENT',message=dict(msg))
        if not lost:schedule(arrive,'message_delivery',msg)
        elif audit is not None:audit(t,'message_bus','MESSAGE_LOST',message_id=mid)
        return msg
    def delivered(self,msg,t,audit=None):
        msg['delivery_status']='delivered';msg['delivered_at']=round(t,4)
        if audit is not None:audit(t,'message_bus','MESSAGE_DELIVERED',message_id=msg['message_id'],recipient=msg['recipient'])
        return msg
