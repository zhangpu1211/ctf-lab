"""通用场景协调器与本地契约适配；生产运行驱动需由可信宿主提供。"""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
import time

from ctflab_contract import ContractError, require
from ctflab_local_service import Observation, Outcome


@dataclass(frozen=True)
class NodeObservation:
    instance_uuid: str
    generation: int
    node: str
    identity: str
    state: str  # stopped / process-running；不推断来宾或课程可用。


class ScenarioCoordinator:
    """driver提供observe/start/stop，必须核验进程、磁盘和网络归属。

    stop只允许正常关机并返回实测退出状态。driver必须自行提供有界超时。
    无driver时仅能离线准备首代磁盘；绝不把空实现当成真实运行。
    """
    def __init__(self, store, *, course_id, baseline_id, driver=None):
        self.store = store
        self.course_id = course_id
        self.baseline_id = baseline_id
        self.driver = driver

    def observations(self, generation):
        require(self.driver is not None, 'capability-unverified')
        plan = self.store.plan(generation)
        result = {}
        for node in plan['start_order']:
            value = self.driver.observe(plan, node, self.store.node_paths(generation, node))
            require(isinstance(value, NodeObservation) and value.instance_uuid == plan['instance_uuid']
                    and type(value.generation) is int and value.generation == generation and value.node == node
                    and value.identity == 'verified' and value.state in ('stopped', 'process-running'), 'identity-unknown')
            result[node] = value
        return result

    def observation_snapshot(self,generation,*,budget=10,monotonic=time.monotonic,utcnow=None):
        """供只读界面使用的有界逐节点采样；不将不完整轮次交给生命周期执行。"""
        require(type(budget) is int and 1<=budget<=30 and self.driver is not None,'capability-unverified')
        utcnow=utcnow or (lambda:datetime.now(timezone.utc));plan=self.store.plan(generation)
        deadline=monotonic()+budget;result={}
        for node in plan['start_order']:
            stamp=utcnow();require(stamp.tzinfo is not None,'identity-unknown')
            item={'instance_uuid':plan['instance_uuid'],'generation':generation,'node':node,'identity':'unknown','state':'unknown',
                  'observed_at':stamp.isoformat()}
            if monotonic()<deadline:
                try:
                    value=self.driver.observe(plan,node,self.store.node_paths(generation,node))
                    require(isinstance(value,NodeObservation) and value.instance_uuid==plan['instance_uuid']
                        and type(value.generation) is int and value.generation==generation and value.node==node
                        and value.identity=='verified' and value.state in ('stopped','process-running'),'identity-unknown')
                    item.update(asdict(value))
                except (OSError,ValueError,RuntimeError,KeyError,TypeError):pass
            result[node]=item
        return result

    def observe(self, context):
        require(context.instance_uuid == self.store.config['instance_uuid'], 'permission-denied')
        snapshot = self.store.snapshot()
        generation = snapshot['active_generation']
        require(generation > 0, 'identity-unknown')
        values = self.observations(generation)
        states = {v.state for v in values.values()}
        state = ('stopped' if states == {'stopped'} else
                 'process-running' if states == {'process-running'} else 'recovery-required')
        if snapshot['unresolved']:
            state = 'recovery-required'
        return Observation('verified', generation, state)

    def preserve_initial_preparation(self, original, replacement):
        # 契约服务还须持工作门锁；此门锁阻止原准备/其他代次操作并行。
        with self.store.locked():
            return self.store.preserve_initial_preparation(original, replacement)

    def execute(self, request, context):
        require(context.instance_uuid == self.store.config['instance_uuid'], 'permission-denied')
        action = request['operation']
        if action in ('prepare', 'reset'):
            require(request['parameters']['baseline_id'] == self.baseline_id, 'state-conflict')
        if action == 'prepare':
            require(request['parameters']['course_id'] == self.course_id, 'state-conflict')
        with self.store.locked():
            snapshot = self.store.snapshot()
            generation = snapshot['active_generation']
            if action == 'recover':
                # 恢复只观测，不重放启动/关机，不删除半成品，不自动选择未提交代次。
                values = self.observations(generation)
                states = {v.state for v in values.values()}
                if len(states) != 1:
                    return Outcome('recovery-required', 'identity-unknown')
                state = 'stopped' if states == {'stopped'} else 'process-running'
                for pending in snapshot['unresolved']:
                    self.store.finish(pending['id'], {'state': 'reconciled', 'observed_state': state,
                                                     'generation': generation, 'automatic_replay': False})
                return Outcome(state)
            expected = 0 if action == 'prepare' else context.generation
            require(generation == expected, 'state-conflict')
            if action=='guest':
                require(not snapshot['unresolved'],'identity-unknown')
                plan=self.store.plan(generation);params=request['parameters'];node=params['node']
                require(node in plan['manifest']['nodes'] and hasattr(self.driver,'guest_command'),'capability-unverified')
                values=self.observations(generation)
                require(all(v.state=='process-running' for v in values.values()),'state-conflict')
                if context.cancel_requested():return Outcome('process-running',cancelled=True)
                extra={k:params[k] for k in ('target_operation_id','expected_sha256') if k in params}
                value=self.driver.guest_command(plan,node,self.store.node_paths(generation,node),params['action'],context.operation_id,**extra)
                if value.get('state')=='unknown' or value.get('error') or value.get('pending'):
                    return Outcome('recovery-required','identity-unknown')
                require(all(v.state=='process-running' for v in self.observations(generation).values()),'identity-unknown')
                return Outcome('process-running',evidence_refs=('guest-'+context.operation_id,))
            if action != 'prepare':
                values = self.observations(generation)
                if action in ('start', 'reset'):
                    require(all(v.state == 'stopped' for v in values.values()), 'state-conflict')
                if action == 'stop':
                    # 已核验全部归属后可停止部分启动的实例；不重放原启动意图。
                    for pending in snapshot['unresolved']:
                        require(pending['action'] in ('start', 'stop'), 'identity-unknown')
                        # 中断关机不可自动重发，须先只读恢复核验。
                        require(pending['action'] == 'start', 'identity-unknown')
                        self.store.finish(pending['id'], {'state': 'reconciled', 'generation': generation,
                                                         'reason': 'verified-before-explicit-stop', 'automatic_replay': False})
            prior = self.store.begin(context.operation_id, action, expected)
            if prior is not None:
                require(prior['state'] in ('prepared', 'stopped', 'process-running'), 'identity-unknown')
                return Outcome(prior['state'])
            if action in ('prepare', 'reset'):
                value = self.store.prepare_generation(context.operation_id, expected, cancelled=context.cancel_requested)
                if value['state'] == 'cancelled':
                    self.store.finish(context.operation_id, value)
                    return Outcome('failed' if action == 'prepare' else 'stopped', cancelled=True)
                return Outcome('prepared')
            plan = self.store.plan(generation)
            order = plan['start_order'] if action == 'start' else plan['stop_order']
            require(action in ('start', 'stop'))
            touched = False
            for node in order:
                if context.cancel_requested():
                    if not touched:
                        if any(v.state != 'stopped' for v in self.observations(generation).values()):
                            return Outcome('recovery-required', 'identity-unknown')
                        self.store.finish(context.operation_id, {'state': 'cancelled', 'generation': generation})
                        return Outcome('stopped', cancelled=True)
                    return Outcome('recovery-required', 'identity-unknown')
                current = self.observations(generation)[node]
                if action == 'stop' and current.state == 'stopped':
                    continue
                self.store.effect(context.operation_id, node, action)
                touched = True
                paths = self.store.node_paths(generation, node)
                if action == 'start':
                    self.driver.start(plan, node, paths, request['parameters'])
                else:
                    self.driver.stop(plan, node, paths)
                observed = self.observations(generation)[node]
                target = 'process-running' if action == 'start' else 'stopped'
                require(observed.state == target, 'stop-timeout' if action == 'stop' else 'identity-unknown')
                self.store.effect(context.operation_id, node, action, {'state': target, 'identity': 'verified'})
            target = 'process-running' if action == 'start' else 'stopped'
            require(all(v.state == target for v in self.observations(generation).values()), 'identity-unknown')
            self.store.finish(context.operation_id, {'state': target, 'generation': generation})
            return Outcome(target)
