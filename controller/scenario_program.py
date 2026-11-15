"""Bounded scenario programs over delivered Core evidence."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import math

from contracts.expressions import Expression, ExpressionError
from contracts.protocol import validate


GRAMMAR='metaevolution.fsm.v1'
TERMINALS={'success','safe_degradation'}
DONE={'op':'eq','left':{'path':'execution.phase_commands_completed'},'right':{'value':True}}


def phase(identifier,commands,on_success,seconds,*,condition=DONE):
    return {'id':identifier,'commands':commands,
            'transition':{'success_when':deepcopy(condition),'on_success':on_success,'on_failure':'fallback'},
            'timeout':{'seconds':seconds,'on_timeout':'fallback'}}


def coalition_rules(*,synthesized=False):
    def binding(name):return {'parameter':name}
    def command(role,action,**parameters):return {'role':role,'action':action,'parameters':parameters}
    channel={'op':'eq','left':{'path':'execution.command_channels.executor'},'right':{'value':True}}
    states=[
        phase('position_relay',[command('relay','move',target=binding('relay_position'))],'enable_relay',50),
        phase('enable_relay',[command('relay','relay',enabled=True)],'wait_channel',12),
        phase('wait_channel',[],'brief_executor' if synthesized else 'approach_target',20,condition=channel),
        phase('approach_target',[command('executor','move',target=binding('target_position'))],'deliver_aid',110),
        phase('deliver_aid',[command('executor','deliver',target_id=binding('target_id'),
                                     resource_id=binding('resource_id'),amount=binding('amount'))],'done',15),
        {'id':'done','outcome':'success'},{'id':'fallback','outcome':'safe_degradation'}]
    if synthesized:
        # Acknowledged peer coordination is an execution dependency, with its
        # own transport budget and fallback.
        states.insert(3,phase('brief_executor',[command('relay','send_message',
            recipient_id=binding('executor_id'),payload={'kind':'relay_route_ready'})],'approach_target',25))
    return {'grammar':GRAMMAR,'initial_state':'position_relay','deadline_seconds':225,'states':states}


def semantic_program(rules):
    """Canonical reachable state graph, independent of names and list order."""
    states={state['id']:state for state in rules['states']}
    initial=rules['initial_state']
    indices={initial:0};queue=deque([initial]);result=[]
    while queue:
        identifier=queue.popleft();state=states[identifier]
        if 'outcome' in state:
            result.append({'outcome':state['outcome']});continue
        transition=state['transition'];timeout=state['timeout']
        references=(transition['on_success'],transition['on_failure'],timeout['on_timeout'])
        for reference in references:
            if reference not in indices:indices[reference]=len(indices);queue.append(reference)
        commands=[(entry['role'],entry['action'],sorted(entry['parameters'])) for entry in state['commands']]
        result.append({'commands':commands,'success_when':transition['success_when'],
                       'edges':[indices[ref] for ref in references]})
    return result


class ProgramError(ValueError):
    pass


class ScenarioProgram:
    def __init__(self,declaration,parameters,assignments,capabilities,*,known_rules=()):
        self.parameters=deepcopy(parameters);self.assignments=dict(assignments)
        self.actions=capabilities['supported_actions']
        schema=declaration.get('parameter_schema',{'type':'object'})
        validate(self.parameters,schema,'INVALID_SCENARIO')
        rules=deepcopy(declaration['execution_rules'])
        self.deadline=rules.get('deadline_seconds')
        if rules.get('grammar')!=GRAMMAR or not self._positive(self.deadline) or self.deadline>86400:
            raise ProgramError('Invalid grammar or execution deadline')
        rows=rules.get('states')
        if not isinstance(rows,list) or not 1<=len(rows)<=16:
            raise ProgramError('A program needs 1..16 states')
        self.states={}
        for state in rows:
            identifier=state.get('id') if isinstance(state,dict) else None
            if not isinstance(identifier,str) or not identifier or identifier in self.states:
                raise ProgramError('Invalid or repeated state identifier')
            self.states[identifier]=state
        self.initial=rules.get('initial_state')
        if not isinstance(self.initial,str) or self.initial not in self.states:
            raise ProgramError('Invalid initial state')
        self._bind_roles(declaration)
        self.commands={};self.conditions={}
        reachable={self.initial};pending=deque([self.initial]);outcomes=set()
        reverse={}
        while pending:
            identifier=pending.popleft()
            state=self.states.get(identifier)
            if state is None:raise ProgramError('Transition targets a missing state')
            if 'outcome' in state:
                if state['outcome'] not in TERMINALS or set(state)!={'id','outcome'}:
                    raise ProgramError('Malformed terminal state')
                outcomes.add(state['outcome']);continue
            self._prepare_state(identifier,state,declaration['allowed_actions'])
            for reference in self._edges(state):
                reverse.setdefault(reference,set()).add(identifier)
                if reference not in reachable:reachable.add(reference);pending.append(reference)
        if reachable!=self.states.keys() or outcomes!=TERMINALS or not any(self.commands.values()):
            raise ProgramError('Require reachable states, commands and both terminal outcomes')
        pending=deque(key for key in reachable if 'outcome' in self.states[key]);can_finish=set(pending)
        while pending:
            for prior in reverse.get(pending.popleft(),()):
                if prior not in can_finish:can_finish.add(prior);pending.append(prior)
        if can_finish!=reachable:raise ProgramError('All phases need a path to a terminal outcome')
        signature=semantic_program(rules)
        if any(signature==semantic_program(reference) for reference in known_rules):
            raise ProgramError('Synthesis repeats an existing program')
        self.started=None;self.entered=None;self.current=self.initial;self.outcome=None
        self.transitions=0;self.references=();self.results={};self.issued=False;self.awaiting_bind=False
        self.trace=[]

    @staticmethod
    def _positive(number):
        return type(number) in (int,float) and math.isfinite(number) and number>0

    @staticmethod
    def _edges(state):
        transition=state['transition']
        return transition['on_success'],transition['on_failure'],state['timeout']['on_timeout']

    def _bind_roles(self,declaration):
        definitions={role['id']:role for role in declaration['roles']}
        self.owners={role:[] for role in definitions}
        for agent,role in self.assignments.items():
            if role not in self.owners:raise ProgramError('Undeclared program role')
            self.owners[role].append(agent)
        for role,owners in self.owners.items():
            rule=definitions[role]
            if not rule['minimum']<=len(owners)<=rule['maximum']:
                raise ProgramError('Program role cardinality')

    def _prepare_state(self,identifier,state,allowed_actions):
        try:transition=state['transition'];timeout=state['timeout'];templates=state['commands']
        except KeyError as error:raise ProgramError('Missing phase field') from error
        if not isinstance(transition,dict) or not isinstance(timeout,dict) or not isinstance(templates,list) or len(templates)>8:
            raise ProgramError('Malformed phase')
        if not self._positive(timeout.get('seconds')) or timeout['seconds']>self.deadline:
            raise ProgramError('Invalid phase timeout')
        try:
            if any(not isinstance(edge,str) or not edge for edge in self._edges(state)):
                raise ProgramError('Invalid phase edge')
            self.conditions[identifier]=Expression(transition['success_when'])
        except (KeyError,ExpressionError) as error:raise ProgramError('Invalid phase transition') from error
        commands=[]
        for template in templates:
            if not isinstance(template,dict):raise ProgramError('Malformed command template')
            role=template.get('role');action=template.get('action');values=template.get('parameters')
            if not isinstance(role,str) or not isinstance(action,str):
                raise ProgramError('Command role and action must be strings')
            owners=self.owners.get(role,())
            if action not in allowed_actions or action not in self.actions or len(owners)!=1 or not isinstance(values,dict):
                raise ProgramError('Command needs a single valid role and an announced action')
            parameters={}
            for key,value in values.items():
                if isinstance(value,dict) and set(value)=={'parameter'}:
                    reference=value['parameter']
                    if not isinstance(reference,str) or reference not in self.parameters:
                        raise ProgramError('Command references an undeclared parameter')
                    value=self.parameters[reference]
                parameters[key]=deepcopy(value)
            validate(parameters,self.actions[action]['parameters_schema'],'INVALID_SCENARIO')
            commands.append({'agent_id':owners[0],'action':action,'parameters':parameters})
        self.commands[identifier]=commands

    @property
    def reserved_agents(self):
        return frozenset(self.assignments)

    def _advance(self,destination,now,reason):
        self.trace.append({'type':'scenario_transition','time':now,'from':self.current,'to':destination,
                           'reason':reason,'commands':[f'{decision}:{index}' for decision,index in self.references]})
        self.current=destination;self.entered=now;self.transitions+=1
        self.references=();self.results={};self.issued=self.awaiting_bind=False

    def propose(self,observation,revision,*,route=None,authorize=None):
        if self.outcome:return []
        now=observation['time']
        if self.started is None:self.started=self.entered=now
        if now-self.started>=self.deadline or self.transitions>=64:
            self.outcome='safe_degradation';self.trace.append({'type':'scenario_budget_exhausted','time':now})
            return []
        agents={agent['id']:agent for agent in observation['agents']}
        for _ in range(16):
            if self.transitions>=64:
                self.outcome='safe_degradation';return []
            state=self.states[self.current]
            if 'outcome' in state:
                self.outcome=state['outcome'];return []
            if now-self.entered>=state['timeout']['seconds']:
                self._advance(state['timeout']['on_timeout'],now,'phase_timeout');continue
            if any(result in ('failed','cancelled','rejected','expired') for result in self.results.values()):
                self._advance(state['transition']['on_failure'],now,'delivered_failure');continue
            commands=self.commands[self.current]
            if commands and not self.issued:
                if self.awaiting_bind:raise ProgramError('Phase commands were proposed without recording their IDs')
                outgoing=[]
                for command in commands:
                    agent=agents.get(command['agent_id'],{})
                    if (revision is not None and agent.get('configuration_revision')!=revision or
                        agent.get('role')!=self.assignments[command['agent_id']] or
                        not self._reachable(agent) or command['action'] not in {a['action'] for a in agent.get('available_actions',())}):
                        return []
                    physical=agent.get('physical',{})
                    if physical.get('carrying') or physical.get('state') in ('loading','unloading','charging','charge_wait'):
                        return []
                    if authorize and not authorize(command,agent):
                        self._advance(state['transition']['on_failure'],now,'command_no_longer_admissible');break
                    adapted=route(command,agent) if route and command['action']=='move' else deepcopy(command)
                    if adapted is None:
                        self._advance(state['transition']['on_failure'],now,'no_feasible_route');break
                    outgoing.append(adapted)
                else:
                    self.awaiting_bind=True;return outgoing
                continue
            completed=not commands or all(self.results.get(ref)=='completed' for ref in self.references)
            channels={role:len(owners)==1 and self._reachable(agents.get(owners[0],{})) for role,owners in self.owners.items()}
            context={'observation':observation,'parameters':self.parameters,
                     'execution':{'phase_commands_completed':completed,'command_channels':channels}}
            try:guard=self.conditions[self.current].evaluate(context,scope='execution_rules')
            except ExpressionError:
                self._advance(state['transition']['on_failure'],now,'invalid_delivered_operand');continue
            if completed and guard is True:
                self._advance(state['transition']['on_success'],now,'delivered_success');continue
            return []
        self.outcome='safe_degradation';return []

    @staticmethod
    def _reachable(agent):
        return agent.get('status') not in (None,'failed','offline','unknown') and agent.get('communication',{}).get('reachable') is True

    def bind(self,decision,indices):
        if not self.awaiting_bind:raise ProgramError('No proposed phase to bind')
        self.references=tuple((decision['decision_id'],index) for index in indices)
        if len(self.references)!=len(self.commands[self.current]):raise ProgramError('Phase command group changed')
        self.issued=True;self.awaiting_bind=False
        self.trace.append({'type':'scenario_phase_dispatch','time':decision['time'],'phase':self.current,
                           'decision_id':decision['decision_id'],'command_indices':list(indices)})

    def observe(self,response):
        for result in response.get('command_results',()):
            ref=(result['decision_id'],result['command_index'])
            if ref not in self.references:continue
            status=result['execution_status']
            if result['validation_status']=='rejected':status='rejected'
            elif result['delivery_status']=='expired':status='expired'
            if self.results.get(ref) not in ('completed','failed','cancelled','rejected','expired'):self.results[ref]=status

    def drain(self):
        traces=self.trace;self.trace=[];return traces
