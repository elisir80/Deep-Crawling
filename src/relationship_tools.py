"""Native outreach, reputation and customer-specific SEO tools."""
from collections import Counter

def backlink_campaign(prospects, budget=0):
    result=[]
    for prospect in prospects or []:
        authority=float(prospect.get('authority',0) or 0); relevance=float(prospect.get('relevance',0) or 0)
        cost=float(prospect.get('cost',1) or 1); expected=(authority*.6+relevance*.4)/cost
        result.append({**prospect,'expected_score':round(expected,4),'recommended':expected>10})
    return {'budget':budget,'prospects':sorted(result,key=lambda x:x['expected_score'],reverse=True)}

def journalist_crm(contacts, interactions=None):
    interactions=interactions or []
    grouped=Counter(x.get('contact') for x in interactions)
    return [{'id':c.get('id'),'name':c.get('name'),'outlet':c.get('outlet'),
             'topics':c.get('topics',[]),'interactions':grouped.get(c.get('id'),0),
             'status':'active' if grouped.get(c.get('id'),0) else 'new'} for c in contacts or []]

def review_quality(reviews):
    result=[]
    for review in reviews or []:
        text=str(review.get('text','')); sentiment=1 if review.get('rating',3)>=4 else -1 if review.get('rating',3)<=2 else 0
        response=str(review.get('response','')); quality=min(100,(len(response)/200)*60+(20 if response else 0)+(20 if review.get('personalized') else 0))
        result.append({'id':review.get('id'),'sentiment':sentiment,'response_quality':round(quality,2),'needs_response':not bool(response)})
    return result

def reputation_crisis(reviews, mentions):
    negatives=sum(1 for x in reviews or [] if (x.get('rating',3) or 3)<=2)
    negative_mentions=sum(1 for x in mentions or [] if x.get('sentiment')=='negative')
    total=len(reviews or [])+len(mentions or [])
    ratio=(negatives+negative_mentions)/max(total,1)
    return {'negative_count':negatives+negative_mentions,'negative_ratio':round(ratio,3),
            'severity':'critical' if ratio>.5 else 'warning' if ratio>.25 else 'normal'}

def customer_scoring(rows, weights=None):
    weights=weights or {'traffic':.3,'revenue':.5,'issues':-.2}; result=[]
    for row in rows or []:
        score=sum(float(row.get(key,0) or 0)*weight for key,weight in weights.items())
        result.append({**row,'customer_score':round(score,4)})
    return sorted(result,key=lambda x:x['customer_score'],reverse=True)
