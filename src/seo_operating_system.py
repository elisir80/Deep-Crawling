"""Safe orchestration primitives for an enterprise SEO operating system."""
from datetime import datetime

def os_workflow(problem, context=None):
    return {'id':datetime.utcnow().strftime('%Y%m%d%H%M%S'),'problem':problem,'context':context or {},
            'state':'discovered','steps':['discover','analyze','simulate','approve','deploy','verify'],
            'human_approval_required':True}

def autonomous_agent(goal, tools=None, max_actions=3, budget=10):
    tools=tools or []
    return {'goal':goal,'allowed_tools':tools[:max_actions],'max_actions':int(max_actions),
            'budget':float(budget),'mode':'simulation_only','kill_switch':True,
            'requires_human_approval':True,'status':'planned'}

def multi_site_twin(sites):
    return {'sites':[{**site,'brand':site.get('brand',site.get('name')),'changes':[]} for site in sites or []],
            'site_count':len(sites or []),'shared_entities':sorted(set.intersection(*[set(s.get('entities',[])) for s in sites]) if sites else set())}

def ecosystem_simulator(metrics, ecosystems=None):
    ecosystems=ecosystems or ['google','bing','youtube','discover','ai-search']
    return [{'ecosystem':name,'baseline':metrics.get(name,0),'scenario':round(float(metrics.get(name,0) or 0)*1.1,2),
             'assumption':'10 percent optimized visibility'} for name in ecosystems]

def causal_impact(treatment, control, pre_period=None, post_period=None):
    pre_period=pre_period or max(len(treatment),1)//2; post_period=post_period or len(treatment)-pre_period
    t_pre=sum(treatment[:pre_period])/max(pre_period,1); t_post=sum(treatment[pre_period:])/max(post_period,1)
    c_pre=sum(control[:pre_period])/max(pre_period,1); c_post=sum(control[pre_period:])/max(post_period,1)
    effect=(t_post-t_pre)-(c_post-c_pre)
    return {'treatment_change':t_post-t_pre,'control_change':c_post-c_pre,'causal_effect':round(effect,4),
            'confidence':round(min(1,abs(effect)/max(abs(t_pre),1)),3),'method':'difference-in-differences'}

def approval_transition(workflow, approved=False):
    return {**workflow,'state':'approved' if approved else 'pending_approval','approved_by':'human' if approved else None}

def execute_guarded(workflow, approved=False):
    if not approved: return {**workflow,'state':'blocked_pending_approval','executed':False}
    return {**workflow,'state':'deployed','executed':True,'rollback_available':True}
