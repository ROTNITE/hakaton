"""Causal observation layers. Only the simulator's sensors read true terrain.
Planner and LLM contexts are built exclusively from delivered observations.
"""
from __future__ import annotations
from world import TerrainSnapshot

class Knowledge:
    def __init__(self,world):
        self.world=world
        self.hazards={};self.smoke={};self.last_seen={};self.agent_seen={};self.agent_hazards={}
        self.changes=[];self.version=0;self._snapshot=None
    def sense_sector(self,sector,t,agent):
        w=self.world;ix=sector%w.sector_count*w.sector_size;iy=sector//w.sector_count*w.sector_size
        truth=w.terrain_at(t);cells=[]
        for y in range(iy,min(w.grid_size,iy+w.sector_size)):
            for x in range(ix,min(w.grid_size,ix+w.sector_size)):
                cells.append([x,y,truth.hazard[y][x],bool(truth.smoke[y][x])])
        self.agent_seen.setdefault(agent,{})[sector]=round(t,4)
        self.agent_hazards.setdefault(agent,{}).update({(x,y):(haz,sm) for x,y,haz,sm in cells})
        return {'sector':sector,'observed_at':round(t,4),'source':agent,'cells':cells}
    def sense_ground(self,cell,t,agent):
        x,y=cell;truth=self.world.terrain_at(t)
        observation={'sector':(y//self.world.sector_size)*self.world.sector_count+(x//self.world.sector_size),
                     'observed_at':round(t,4),'source':agent,
                     'cells':[[x,y,truth.hazard[y][x],bool(truth.smoke[y][x])]]}
        self.agent_seen.setdefault(agent,{})[observation['sector']]=round(t,4)
        self.agent_hazards.setdefault(agent,{})[(x,y)]=(truth.hazard[y][x],bool(truth.smoke[y][x]))
        return observation
    def merge_delivered(self,observation,delivered_at):
        """Merge only after receipt, retain timestamp for independent reconstruction."""
        sec=observation['sector'];observed_at=observation['observed_at']
        if observed_at>=self.last_seen.get(sec,-1):self.last_seen[sec]=observed_at
        updated=[];change=False
        for x,y,hazard,smoke in observation['cells']:
            key=(x,y)
            old=self.hazards.get(key)
            # A fresher report wins; do not overwrite new readings with old packets.
            if old is not None and old[1]>observed_at:continue
            # Unknown is initially assumed traversable for planning, but not asserted as observed.
            if (old[0] if old is not None else None)!=hazard or self.smoke.get(key,(False,-1))[0]!=smoke:change=True
            self.hazards[key]=(hazard,observed_at)
            self.smoke[key]=(smoke,observed_at)
            updated.append([x,y,hazard,smoke])
        if change:self.version+=1;self._snapshot=None
        report={'t':round(delivered_at,4),'observed_at':observed_at,'sector':sec,
                'source':observation['source'],'cells':updated,'version':self.version}
        self.changes.append(report)
        return report
    def snapshot(self):
        if self._snapshot is None:
            n=self.world.grid_size
            hazard=[[None]*n for _ in range(n)];smoke=[[False]*n for _ in range(n)]
            for (x,y),(kind,_) in self.hazards.items():hazard[y][x]=kind
            for (x,y),(flag,_) in self.smoke.items():smoke[y][x]=flag
            self._snapshot=TerrainSnapshot(self.world.grid,hazard,smoke,10_000+self.version)
        return self._snapshot
    def local_snapshot(self,agent):
        # Agent's own readings augment only the locally known cells.
        base=self.snapshot();local=self.agent_hazards.get(agent,{})
        if not local:return base
        h=[row[:] for row in base.hazard];s=[row[:] for row in base.smoke]
        for (x,y),(kind,flag) in local.items():h[y][x]=kind;s[y][x]=flag
        return TerrainSnapshot(self.world.grid,h,s,20_000+self.version)
    def hazard_summary(self,limit=36):
        cells=[{'cell':[x,y],'kind':kind,'observed_at':at} for (x,y),(kind,at) in self.hazards.items() if kind]
        return sorted(cells,key=lambda e:-e['observed_at'])[:limit]
    def recent_sectors(self,t,limit=20):
        return [{'sector':s,'last_seen':ts,'age':round(t-ts,2)}
                for s,ts in sorted(self.last_seen.items(),key=lambda p:p[1])[:limit]]
