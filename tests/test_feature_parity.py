"""Local regression coverage for LibreCrawl's SEO Spider parity features."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
import tempfile
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from bs4 import BeautifulSoup

from src.core.seo_extractor import SEOExtractor
from src.core.seo_utilities import apply_cdn, generate_sitemap, generate_sitemap_index, segment_urls, test_robots
from src.core.link_manager import LinkManager
from src.core.content_analysis import analyze_content
from src.core.advanced_analysis import detect_changes, embedding_search, orphan_pages, semantic_search
from src.core.link_metrics import calculate_link_metrics
from src.integrations import backlink_metrics
from src.crawl_db import init_crawl_tables, load_crawled_urls, save_url_batch
from src.crawler import WebCrawler


class FeatureParityTests(unittest.TestCase):

    def test_project_round_trip(self):
        from src.project_manager import export_project, import_project, restore_project
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'sample.librecrawl')
            export_project(path, {'id': 1, 'base_url': 'https://example.com'}, [{'url': 'https://example.com'}], [], [], {'maxDepth': 2})
            project = import_project(path)
            self.assertEqual(project['manifest']['format'], 'librecrawl-project')
            self.assertEqual(project['urls'][0]['url'], 'https://example.com')
            restored = restore_project(path, 1, 'test-import')
            self.assertEqual(restored['status'], 'completed')
            self.assertEqual(restored['url_count'], 1)

    def test_ahrefs_local_workflows(self):
        from src.ahrefs_tools import batch_analysis, domain_comparison, content_gap, link_intersect, keyword_opportunities
        rows = [{'url':'https://a.test/one','title':'SEO guide','content_text':'keyword strategy'}]
        self.assertEqual(batch_analysis(rows)[0]['domain'], 'a.test')
        self.assertEqual(domain_comparison({'a': rows})[0]['urls'], 1)
        self.assertTrue(content_gap({'a': rows, 'b': [{'url':'https://b.test','title':'SEO guide'}]}))
        self.assertTrue(link_intersect({'a':[{'target_url':'https://x.test'}], 'b':[{'target_url':'https://x.test'}]}))
        self.assertTrue(keyword_opportunities(rows))

    def test_native_seo_intelligence(self):
        from src.native_seo_intelligence import keyword_index, authority_score, traffic_estimate, record_ranking
        rows = [{'url':'https://a.test','title':'SEO guide','h1':'SEO','meta_description':'Guide','content_text':'keyword strategy','status_code':200,'internal_links':3}]
        self.assertTrue(keyword_index(rows))
        self.assertGreaterEqual(authority_score(rows)['score'], 0)
        self.assertEqual(traffic_estimate([{'keyword':'seo','position':1,'search_volume':1000}])['estimated_monthly_visits'], 285.0)
        self.assertEqual(record_ranking(rows, [{'keyword':'seo','position':1}])[0]['source'], 'imported')

    def test_native_priority_seo_tools(self):
        from src.native_seo_tools import serp_analyze, cluster_keywords, cannibalization, internal_link_suggestions, content_decay, rank_snapshot, rank_tracker_report
        self.assertEqual(serp_analyze('<title>SEO</title><a href=\"https://a.test\">Result</a>','a.test')['result_count'],1)
        self.assertEqual(len(cluster_keywords(['best SEO tool','buy SEO service'])),2)
        rows=[{'url':'https://a.test/1','title':'SEO guide','h1':'SEO','word_count':100},{'url':'https://a.test/2','title':'SEO tips','h1':'SEO','word_count':50}]
        self.assertTrue(cannibalization(rows)); self.assertTrue(internal_link_suggestions(rows,[]))
        self.assertEqual(content_decay([rows[0]], [{'url':'https://a.test/1','word_count':50}])[0]['url'],'https://a.test/1')
        self.assertEqual(rank_snapshot('seo','https://a.test',1,'IT','mobile')['device'],'mobile')
        history=[{'keyword':'seo','url':'https://a.test','position':10,'country':'IT','device':'mobile','captured_at':'2026-01-01','serp_features':['ai_overview']},{'keyword':'seo','url':'https://a.test','position':4,'country':'IT','device':'mobile','captured_at':'2026-01-02','serp_features':['paa']},{'keyword':'seo','competitor':'competitor.test','position':7,'country':'IT','device':'mobile','captured_at':'2026-01-02'}]
        report=rank_tracker_report(history); self.assertEqual(report['rows'][0]['position_change'],6.0); self.assertTrue(report['rows'][0]['ai_overview'])
        self.assertEqual(report['competitors'][0]['competitor'],'competitor.test')

    def test_native_link_indexability_sitemap_tools(self):
        from src.core.seo_utilities import analyze_link_reclamation, redirect_map, sitemap_monitor, indexability_simulator, generate_special_sitemap
        rows=[{'url':'https://a.test/old','status_code':404},{'url':'https://a.test/new','status_code':301,'redirects':['https://a.test/final']}]
        links=[{'source_url':'https://a.test','target_url':'https://a.test/old','anchor_text':'old'}]
        self.assertEqual(analyze_link_reclamation(rows,links)[0]['status_code'],404)
        self.assertEqual(len(redirect_map(rows)),1)
        self.assertEqual(sitemap_monitor(['https://a.test/old'],rows)['coverage_percent'],100.0)
        self.assertFalse(indexability_simulator({'url':'https://a.test','robots':'noindex'})['indexable'])
        self.assertIn('sitemap',generate_special_sitemap([{'url':'https://a.test'}],'news'))

    def test_technical_seo_tools(self):
        from src.technical_seo_tools import schema_audit, record_cwv, cwv_history, parse_access_log
        self.assertTrue(schema_audit({'schema_org':[{'@type':'Article'}]})['rich_result_eligible'])
        cwv=record_cwv('https://a.test',{'lcp':1.2,'inp':50,'cls':0.02},'2026-01-01')
        self.assertTrue(cwv['passed']); self.assertEqual(len(cwv_history([cwv])[0]['snapshots']),1)
        log='127.0.0.1 - - [01/Jan/2026:00:00:00 +0000] \"GET / HTTP/1.1\" 200 10 \"-\" \"GPTBot/1.0\"'
        self.assertEqual(parse_access_log([log])['summary']['GPTBot'],1)

    def test_vertical_audits(self):
        from src.vertical_seo_audits import image_audit, accessibility_seo_audit, local_audit, ecommerce_audit, international_audit, programmatic_audit, competitor_content
        row={'url':'https://a.test/product/1','title':'Product SEO','content_text':'address phone price offers','images':[{'src':'x.jpg'}],'schema_org':[{'@type':'Product','offers':{}}]}
        self.assertTrue(image_audit([row])); self.assertTrue(accessibility_seo_audit([{'url':'x','accessibility':[{'issue':'alt'}]}])[0]['seo_risk'])
        self.assertTrue(local_audit([row])[0]['nap']['address']); self.assertTrue(ecommerce_audit([row])[0]['product_detected'])
        self.assertTrue(international_audit([row])[0]['issues']); self.assertTrue(programmatic_audit([row]))
        self.assertIn('shared_terms',competitor_content([row],[{'content_text':'Product SEO'}]))

    def test_strategy_tools(self):
        from src.seo_strategy import seo_score, forecast, recommendations, changes, white_label_report
        rows=[{'url':'https://a.test','status_code':200,'title':'Title','meta_description':'Description'}]
        self.assertGreater(seo_score(rows)['score'],0)
        self.assertEqual(len(forecast([{'value':10},{'value':20}])['scenarios']['realistic']),6)
        self.assertTrue(recommendations([{'url':'x','status_code':404}]))
        self.assertEqual(changes([{'url':'x','title':'old'}],[{'url':'x','title':'new'}])[0]['type'],'changed')
        self.assertIn('summary',white_label_report({'name':'x'},rows))

    def test_snapshot_persistence(self):
        from src.crawl_db import init_crawl_tables, save_rank_snapshot, list_rank_snapshots, save_cwv_snapshot, list_cwv_snapshots
        init_crawl_tables()
        rank_id=save_rank_snapshot(999, {'keyword':'seo-competitor','url':'https://x.test','position':3,'competitor':'competitor.test','captured_at':'2026-01-01T00:00:00Z'})
        cwv_id=save_cwv_snapshot(999, {'url':'https://x.test','lcp':1.2,'passed':True,'snapshot':'2026-01-01T00:00:00Z'})
        self.assertGreater(rank_id,0); self.assertEqual(list_rank_snapshots(999,'seo-competitor')[0]['keyword'],'seo-competitor'); self.assertEqual(list_rank_snapshots(999,'seo-competitor')[0]['competitor'],'competitor.test')
        self.assertGreater(cwv_id,0); self.assertEqual(list_cwv_snapshots(999,'https://x.test')[0]['passed'],1)

    def test_log_budget_and_gsc_helpers(self):
        from src.technical_seo_tools import parse_access_log
        from src.log_seo_tools import crawl_budget, bot_frequency
        log='127.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "GET /?sort=x HTTP/1.1" 404 10 "-" "Googlebot/2.1"'
        report=parse_access_log([log]); budget=crawl_budget(report,[{'url':'/known'}])
        self.assertEqual(budget['googlebot_requests'],1); self.assertEqual(budget['wasted_requests'],1)
        self.assertEqual(bot_frequency(report)[0]['bot'],'Googlebot')

    def test_serp_and_javascript_tools(self):
        from src.serp_js_tools import serp_features, feature_volatility, js_seo_debug
        self.assertIn('featured_snippet',serp_features({'text':'Featured Snippet and People Also Ask'})['features'])
        self.assertEqual(feature_volatility([{'keyword':'seo','features':['video']}],[{'keyword':'seo','features':['images']}])['volatile_keywords'],1)
        result=js_seo_debug({'source_html':'<a href=\"/a\">A</a>','html':'<div id=\"reactroot\"><a href=\"/a\">A</a><a href=\"/b\">B</a></div>'})
        self.assertEqual(result['links_added_after_render'],['/b']); self.assertTrue(result['hydration_detected'])

    def test_content_intelligence(self):
        from src.content_intelligence import entities, topical_map, semantic_score, eat_audit, near_duplicates, freshness, editorial_plan
        rows=[{'url':'https://x.test/a','title':'Google SEO Guide','content_text':'Google SEO Guide author experience https://source.test','schema_org':[{'@type':'Article'}],'lastmod':'2024-01-01'},
              {'url':'https://x.test/b','content_text':'Google SEO Guide author experience https://source.test','lastmod':'2024-01-01'}]
        self.assertTrue(entities(rows)[0]['schema_types']); self.assertTrue(topical_map(rows))
        self.assertGreater(semantic_score(rows[0],['google','seo'])['score'],0); self.assertEqual(eat_audit(rows)[0]['score'],75)
        self.assertTrue(near_duplicates(rows)); self.assertEqual(freshness(rows)[0]['status'],'stale'); self.assertTrue(editorial_plan(rows))

    def test_automation_tools(self):
        from src.seo_automation import staging_diff, redirect_plan, regression_tests, incidents, experiment_variant
        self.assertTrue(staging_diff([{'url':'x','title':'new'}],[{'url':'x','title':'old'}]))
        self.assertTrue(redirect_plan(['https://x/old'],['https://x/new']))
        self.assertFalse(regression_tests([{'url':'x','status_code':404,'title':''}])['passed'])
        self.assertEqual(incidents([{'url':'x','status_code':200}],[{'url':'x','status_code':500}])[0]['severity'],'critical')
        self.assertEqual(experiment_variant('x','Title','B')['status'],'draft')

    def test_aeo_and_crawl_controls(self):
        from src.aeo_crawl_controls import prompt_visibility, brand_mentions, ai_crawler_policy, crawl_space_audit, pagination_audit
        visible=prompt_visibility('best seo tool',[{'provider':'test','text':'LibreCrawl is useful','citations':['x']}],['librecrawl'])
        self.assertEqual(visible['visibility_percent'],100.0)
        self.assertTrue(brand_mentions([{'url':'x','text':'LibreCrawl mention'}],['LibreCrawl']))
        self.assertIn('GPTBot',ai_crawler_policy('User-agent: GPTBot\\nDisallow: /private/')['policies'])
        space=crawl_space_audit(['https://x.test/a?color=red&size=l&sort=price&page=2'])
        self.assertTrue(space['crawl_traps']); self.assertTrue(pagination_audit([{'url':'https://x.test/page/2'}]))

    def test_feed_local_hreflang_tools(self):
        from src.vertical_seo_audits import product_feed_audit, local_citations, hreflang_graph, javascript_sitemap_discovery
        self.assertFalse(product_feed_audit([{'id':'1','link':'x'}])[0]['valid'])
        self.assertTrue(local_citations([{'source':'x','name':'A','address':'B','phone':'C'}])[0]['consistent'])
        graph=hreflang_graph([{'url':'/it','hreflang':[{'lang':'en','href':'/en'}]},{'url':'/en','hreflang':[{'lang':'it','href':'/it'}]}])
        self.assertFalse(graph['issues'])
        self.assertTrue(javascript_sitemap_discovery([{'url':'/','html':'<a href=\"/dynamic\">x</a>'}]))

    def test_professional_orchestration(self):
        from src.professional_tools import SEO_TOOL_CATALOG, discover_news_audit, register_plugin, workflow_payload
        self.assertIn('gsc-report',SEO_TOOL_CATALOG); self.assertTrue(discover_news_audit([{'url':'x','publication_date':'2026-01-01'}])[0]['news_detected'])
        self.assertTrue(register_plugin('p','Plugin')['enabled'])
        self.assertEqual(workflow_payload('github','Fix','Description')['title'],'Fix')

    def test_final_named_tools(self):
        from src.content_intelligence import citation_fact_audit, schema_graph
        from src.vertical_seo_audits import multi_location_dashboard
        from src.core.link_metrics import backlink_quality_audit
        from src.seo_strategy import budget_forecast
        self.assertTrue(citation_fact_audit([{'url':'x','content_text':'According to https://source.test data'}])[0]['citation_coverage'])
        self.assertTrue(schema_graph([{'url':'x','schema_org':[{'@id':'x','@type':'Article'}]}])['nodes'])
        self.assertEqual(multi_location_dashboard([{'name':'Rome','rows':[]}])[0]['location'],'Rome')
        self.assertTrue(backlink_quality_audit([{'target_url':'x','target_status':404}])[0]['lost'])
        self.assertIn('expected_value',budget_forecast([{'value':10}],100))

    def test_second_generation_priority_tools(self):
        from src.advanced_next import knowledge_graph, topic_gap, search_intent, algorithm_update_detector, causal_forecast, impact_simulator
        graph=knowledge_graph([{'url':'x','title':'SEO','named_entities':['Google'],'schema_org':[{'@type':'Article'}]}])
        self.assertTrue(graph['nodes']); self.assertTrue(topic_gap([{'content_text':'seo'}],['seo','ecommerce'])[1]['priority']=='high')
        self.assertEqual(search_intent('best SEO tool')['intent'],'commercial')
        self.assertTrue(algorithm_update_detector([{'clicks':100},{'clicks':150}])['detected'])
        self.assertEqual(len(causal_forecast([{'value':10},{'value':20}],horizon=3)['forecast']),3)
        self.assertGreater(impact_simulator([{'url':'x','status_code':200}],{'title':'New'})[0]['delta'],0)

    def test_data_operations(self):
        from src.data_operations import audit_replay, time_travel_compare, data_lake_export, sql_like_query, sla_monitor, remediation_queue, ai_cost_report, private_mode
        events=[{'timestamp':'2026-01-01','key':'score','value':10},{'timestamp':'2026-02-01','key':'score','value':20}]
        self.assertEqual(audit_replay(events,'2026-01-15')['state']['score'],10)
        self.assertTrue(time_travel_compare(events,'2026-01-01','2026-03-01'))
        self.assertIn('url',data_lake_export([{'url':'x'}])); self.assertTrue(sql_like_query([{'url':'x'}],'url','x'))
        self.assertTrue(sla_monitor([{'severity':'high','age_hours':30}])[0]['sla_breached'])
        self.assertEqual(remediation_queue([{'severity':'critical'}])[0]['priority'],'critical')
        self.assertEqual(ai_cost_report([{'cost':.1,'tokens':10}])['tokens'],10); self.assertTrue(private_mode({})['enabled'])

    def test_infrastructure_tools(self):
        from src.infrastructure_tools import render_queue, preview_fix, contract_test, security_privacy_audit
        self.assertEqual(render_queue(['x'],3)['workers'],3)
        self.assertEqual(preview_fix({'url':'x','title':'old'},{'title':'new'})['after']['title'],'new')
        self.assertTrue(contract_test('schema',{'valid':True},{'valid':True})['passed'])
        self.assertTrue(security_privacy_audit({'url':'https://x','http_headers':{'strict-transport-security':'max-age=1'}})['hsts'])

    def test_enterprise_core(self):
        from src.enterprise_core import digital_twin, rollback_patch, explain, lineage, immutable_audit, ownership, permission_matrix
        twin=digital_twin([{'url':'x','title':'old'}],{'x':{'title':'new'}})
        self.assertEqual(twin['diffs'][0]['changes']['title']['after'],'new')
        self.assertEqual(rollback_patch(twin)['status'],'rollback-ready')
        self.assertEqual(explain('score',80,{},'weighted')['confidence'],.8)
        self.assertEqual(lineage('score','crawl')['quality'],1.0)
        self.assertEqual(len(immutable_audit({'x':1})['hash']),64)
        self.assertEqual(ownership('x','alice')['owner'],'alice'); self.assertIn('deploy',permission_matrix('a',[],'admin')['permissions'])

    def test_enterprise_gateway(self):
        from src.enterprise_gateway import graphql_query, webhook_event, enterprise_security
        self.assertEqual(graphql_query('{ health }')['data']['health']['status'],'ok')
        self.assertEqual(len(webhook_event('seo',{})['id']),16)
        self.assertTrue(enterprise_security({'encryption_key':'k','sso_provider':'saml'})['sso'])

    def test_realtime_enterprise_tools(self):
        from src.realtime_enterprise import update_heatmap, causal_attribution, ranking_experiment, serp_replay, adaptive_scheduler, demand_graph, market_gap, entity_conflicts, authority_decay, content_revenue, safe_deploy
        self.assertEqual(update_heatmap([{'url':'x','position':1}],[{'url':'x','position':5}])['affected'],1)
        self.assertEqual(causal_attribution([{'channel':'seo','revenue':100}])[0]['share_percent'],100)
        self.assertEqual(ranking_experiment('x',[{'position':2}],{'B':[{'position':1}]})['variants'][0]['delta'],-1)
        self.assertTrue(serp_replay(['a'],['b'])['changed']); self.assertEqual(adaptive_scheduler([{'url':'x','priority':5}],budget=1)['selected'],['x'])
        self.assertTrue(demand_graph([{'keyword':'seo','volume':10,'growth':30}],['IT'])[0]['emerging'])
        self.assertTrue(market_gap({'IT':{'terms':['seo']},'EN':{'terms':[]}})[1]['missing_terms'])
        self.assertFalse(entity_conflicts({'schema_entities':['A'],'content_entities':['B']})['consistent'])
        self.assertTrue(authority_decay([100,70])['decayed']); self.assertEqual(content_revenue([{'url':'x','revenue':10,'sessions':2}])[0]['revenue_per_session'],5.0)
        self.assertEqual(safe_deploy([],0)['status'],'pending_approval')

    def test_enterprise_intelligence(self):
        from src.enterprise_intelligence import causal_graph, anomaly_explainer, observability, intent_drift, query_satisfaction, zero_click_visibility, misinformation_check, freshness_prediction
        self.assertTrue(causal_graph([{'change':'title','ranking':'up','traffic':'up','conversion':'up'}])['edges'])
        self.assertTrue(anomaly_explainer({'clicks':50},{'clicks':100})['anomalies'])
        self.assertEqual(observability([{'score':-1}])['alerts'][0]['severity'],'warning')
        self.assertEqual(intent_drift([{'keyword':'seo','intent':'info'}],[{'keyword':'seo','intent':'commercial'}])['count'],1)
        self.assertGreater(query_satisfaction([{'query':'seo','ctr':.5,'position':1}])[0]['score'],0)
        self.assertTrue(zero_click_visibility([{'query':'seo','ai_overview':True}])[0]['zero_click'])
        self.assertEqual(misinformation_check('x',['bad'],['good'])['risk'],'high')
        self.assertEqual(freshness_prediction([{'url':'x','age_days':800}])[0]['action'],'refresh')

    def test_enterprise_next_tools(self):
        from src.enterprise_next import serp_visual_diff, cannibalization_plan, topical_benchmark, pagerank_recommendations, link_attack_detector, rollback_guardrail, evidence_snapshot
        self.assertTrue(serp_visual_diff('<h1>A</h1>','<h1>B</h1>')['changed'])
        rows=[{'url':'a','title':'SEO guide','traffic':10},{'url':'b','title':'SEO guide','traffic':1}]
        self.assertTrue(cannibalization_plan(rows)); self.assertEqual(topical_benchmark(['seo'],['seo','ecommerce'])['missing'],['ecommerce'])
        self.assertTrue(pagerank_recommendations([{'url':'a','title':'seo','content_text':'seo topic'},{'url':'b','title':'topic'}],[]))
        links=[{'source_url':'x','target_url':str(i)} for i in range(101)]
        self.assertTrue(link_attack_detector(links)); self.assertTrue(rollback_guardrail(['a'],[{'url':'b','status_code':500}])['rollback_required'])
        self.assertEqual(len(evidence_snapshot({'a':1})['sha256']),64)

    def test_commerce_ai_geo_tools(self):
        from src.enterprise_commerce import ai_citation_ownership, hallucination_monitor, margin_optimizer, inventory_canonical, hreflang_deployment_check, geo_test, cdn_indexability_conflicts
        self.assertEqual(ai_citation_ownership(['p'],'brand',[{'prompt':'p','source':'brand.com'}])[0]['ownership_percent'],100)
        self.assertEqual(hallucination_monitor([{'claims':['bad']}],['good'])[0]['risk'],'high')
        self.assertEqual(margin_optimizer([{'url':'x','margin':10,'traffic':100,'conversion_rate':.1}])[0]['priority'],'high')
        self.assertEqual(inventory_canonical([{'url':'x','stock':0,'alternative_url':'y'}])[0]['canonical'],'y')
        self.assertFalse(hreflang_deployment_check([{'url':'x','required_languages':['it'],'hreflang':[]}])['passed'])
        self.assertEqual(len(geo_test(['x'],['IT','EN'])),2)
        self.assertTrue(cdn_indexability_conflicts([{'url':'x','http_headers':{'cache-control':'a'},'edge_headers':{'cache-control':'b'}}]))

    def test_enterprise_operations(self):
        from src.enterprise_operations import googlebot_prediction, crawl_budget_cost, adaptive_recrawl, content_capacity, seo_roi, multi_touch_attribution, executive_report
        self.assertTrue(googlebot_prediction([{'url':'x','priority':10}]))
        self.assertEqual(crawl_budget_cost([{'size':10}])['requests'],1)
        self.assertEqual(adaptive_recrawl([{'url':'x','priority':5}],1)['queue'],['x'])
        self.assertTrue(content_capacity([{'effort_days':2}],people=1,days=1)['overloaded'])
        self.assertGreater(seo_roi([{'cost':10,'revenue':20}])[0]['roi'],0)
        self.assertEqual(multi_touch_attribution([{'touchpoints':['seo','brand'],'revenue':100}])[0]['revenue'],50)
        self.assertIn('evidence_required',executive_report([]))

    def test_enterprise_platform(self):
        from src.enterprise_platform import event_append, event_replay, compliance_policy, ai_registry, plugin_security, stream_event, voice_command, agent_plan
        first=event_append('seo',{'op':'set','key':'score','value':10})
        self.assertEqual(len(first['hash']),64); self.assertEqual(event_replay([first])['score'],10)
        self.assertTrue(compliance_policy({'encrypted':True,'audit_log':True})['passed'])
        self.assertTrue(ai_registry([{'id':'local','local':True}])[0]['local'])
        self.assertTrue(plugin_security({'id':'p','signature':'s','scopes':[]})['signed'])
        self.assertEqual(stream_event({'type':'seo'})['status'],'queued')
        self.assertEqual(voice_command('genera report')['intent'],'report')
        self.assertTrue(agent_plan('audit')['approval_required'])

    def test_relationship_tools(self):
        from src.relationship_tools import backlink_campaign, journalist_crm, review_quality, reputation_crisis, customer_scoring
        self.assertTrue(backlink_campaign([{'authority':80,'relevance':90,'cost':5}])['prospects'][0]['recommended'])
        self.assertEqual(journalist_crm([{'id':'j','name':'J'}],[{'contact':'j'}])[0]['status'],'active')
        self.assertTrue(review_quality([{'id':'r','rating':1}])[0]['needs_response'])
        self.assertEqual(reputation_crisis([{'rating':1}],[{'sentiment':'negative'}])['severity'],'critical')
        self.assertGreater(customer_scoring([{'traffic':10,'revenue':10}])[0]['customer_score'],0)

    def test_seo_operating_system(self):
        from src.seo_operating_system import os_workflow, autonomous_agent, multi_site_twin, ecosystem_simulator, causal_impact, approval_transition, execute_guarded
        workflow=os_workflow('missing titles'); self.assertTrue(workflow['human_approval_required'])
        self.assertTrue(autonomous_agent('audit')['kill_switch'])
        self.assertEqual(multi_site_twin([{'name':'A','entities':['SEO']},{'name':'B','entities':['SEO']}])['shared_entities'],['SEO'])
        self.assertEqual(len(ecosystem_simulator({'google':10})),5)
        self.assertGreater(causal_impact([10,20,30,40],[10,15,20,25])['causal_effect'],0)
        approved=approval_transition(workflow,True); self.assertTrue(execute_guarded(approved,True)['executed'])

    def test_enterprise_market_and_risk(self):
        from src.enterprise_market import (update_clustering, serp_market_intelligence, demand_early_warning,
            competitor_action_monitor, vulnerability_scan, technical_debt, financial_risk,
            portfolio_forecast, budget_allocator, content_supply_chain)
        self.assertTrue(update_clustering([{'date':'u1','impact':.3,'market':'IT'}])[0]['significant'])
        self.assertEqual(serp_market_intelligence([{'market':'IT','device':'mobile','position':2}])[0]['average_position'],2)
        self.assertTrue(demand_early_warning([{'keyword':'seo','previous':10,'current':20}])[0]['early_warning'])
        self.assertEqual(competitor_action_monitor([], [{'url':'/new'}])[0]['action'],'new_url')
        self.assertFalse(vulnerability_scan([{'url':'/a','admin_exposed':True}])['passed'])
        self.assertEqual(technical_debt([{'url':'/a','missing_title':True}])[0]['debt_level'],'medium')
        self.assertGreater(financial_risk([{'revenue':1000,'probability':.5}])[0]['revenue_at_risk'],0)
        self.assertEqual(len(portfolio_forecast([10],2)['forecast']),2)
        self.assertEqual(sum(x['allocation'] for x in budget_allocator([{'impact':1},{'impact':1}],100)),100)
        self.assertTrue(content_supply_chain([{'stage':'review','approval_required':True}])['items'][0]['blocked'])

    def test_enterprise_compliance_reputation_commerce(self):
        from src.enterprise_compliance import (ai_approval_gate, authorship_provenance, legal_content_scan,
            brand_safety_scan, knowledge_panel_monitor, entity_reputation, local_competitor_monitor,
            map_volatility, marketplace_audit, feed_sitemap_canonical_graph)
        self.assertEqual(ai_approval_gate({'claims':['fact'],'citations':['src'],'human_approved':True}, ['fact'])['decision'], 'publish')
        self.assertTrue(authorship_provenance([{'author':'A'}])[0]['traceable'])
        self.assertFalse(legal_content_scan([{'url':'/a','copyright_risk':True}])['passed'])
        self.assertFalse(brand_safety_scan([{'id':'x','text':'malware'}])['safe'])
        self.assertTrue(knowledge_panel_monitor({'name':'A'},{'name':'B'})['changed'])
        self.assertEqual(entity_reputation([{'text':'Brand','sentiment_score':-1}], 'Brand')['mentions'],1)
        self.assertEqual(local_competitor_monitor([], [{'name':'C'}])[0]['action'],'new')
        self.assertTrue(map_volatility([{'keyword':'x','rank':1},{'keyword':'x','rank':5}])[0]['alert'])
        self.assertFalse(marketplace_audit([{'id':'1'}])['valid'])
        self.assertFalse(feed_sitemap_canonical_graph([], [{'url':'/a'}], [{'url':'/a','canonical':'/b'}])['passed'])

    def test_enterprise_resilience_observability(self):
        from src.enterprise_resilience import (migration_rehearsal, disaster_recovery_snapshot, rum_summary,
            synthetic_monitor, privacy_safe_analytics, accessibility_sustainability, edge_policy_simulator, cdn_purge_plan)
        self.assertFalse(migration_rehearsal([{'url':'/old'}], [], {})['passed'])
        self.assertTrue(disaster_recovery_snapshot('p', [{'id':1}])['restore_ready'])
        self.assertEqual(rum_summary([{'lcp':1,'inp':2,'cls':.1,'ttfb':3}])['metrics']['lcp']['average'],1)
        self.assertFalse(synthetic_monitor([{'url':'/','status_code':500}])['passed'])
        self.assertNotIn('email', privacy_safe_analytics([{'email':'x','country':'IT'}])['events'][0])
        self.assertFalse(accessibility_sustainability({'accessibility':{'missing_alt':1}})['accessibility_passed'])
        self.assertTrue(edge_policy_simulator([{'url':'/'}], {'headers':{'x-robots-tag':'noindex'}})['results'][0]['indexable'] is False)
        self.assertFalse(cdn_purge_plan([{'url':'/'}])['executed'])

    def test_enterprise_governance_index_reports(self):
        from src.enterprise_governance import (identity_policy, mask_fields, federated_aggregate, local_index,
            certify_plugin, reproducible_report, knowledge_base, penalty_risk, procurement_questionnaire,
            review_response_plan, ecommerce_autopilot)
        self.assertTrue(identity_policy({'sso_provider':'saml'})['sso_enabled'])
        self.assertEqual(mask_fields([{'email':'x','country':'IT'}])[0]['email'],'[REDACTED]')
        self.assertEqual(federated_aggregate([{'rows':[{'dimension':'IT','value':2}]}])['aggregated'][0]['value'],2)
        self.assertEqual(local_index([{'url':'/a','title':'SEO audit'}],'SEO')['urls'],['/a'])
        self.assertEqual(certify_plugin({'id':'p','signature':'sig','scopes':['read']})['status'],'certified')
        self.assertTrue(reproducible_report({'score':1})['reproducible'])
        self.assertEqual(knowledge_base([{'topic':'migration','decision':'redirect'}],'migration')[0]['topic'],'migration')
        self.assertEqual(penalty_risk([{'spam_signal':True}])[0]['risk'],'medium')
        self.assertFalse(procurement_questionnaire({'sso_provider':'saml'})['passed'])
        self.assertTrue(review_response_plan([{'id':'r','rating':1}])[0]['requires_human_approval'])
        self.assertFalse(ecommerce_autopilot([{'url':'/p','stock':0}])['items'][0]['executed'])

    def test_enterprise_connectors_and_sandbox(self):
        from src.enterprise_connectors import connector_readiness, semantic_query, agent_sandbox_check, signed_bundle, call_connector
        readiness=connector_readiness({'site_url':'https://x.test','access_token':'token'})
        self.assertTrue(readiness['connectors']['gsc']['ready'])
        self.assertFalse(readiness['connectors']['ga4']['ready'])
        self.assertEqual(semantic_query([{'url':'/a','title':'SEO audit'}],'SEO')[0]['url'],'/a')
        self.assertTrue(agent_sandbox_check({'allowed_tools':['crawl'],'kill_switch':True,'requires_human_approval':True,'budget':1,'max_actions':1},['crawl'])['safe'])
        self.assertFalse(agent_sandbox_check({'allowed_tools':['crawl','deploy'],'kill_switch':True,'requires_human_approval':True,'budget':1,'max_actions':1},['crawl','deploy'])['safe'])
        self.assertEqual(len(signed_bundle({'score':1})['sha256']),64)
        with self.assertRaises(ValueError):
            call_connector('unknown', 'http://127.0.0.1:1')
        from src.integrations import search_console
        class MockResponse:
            content=b'{"rows":[]}'
            def raise_for_status(self): pass
            def json(self): return {'rows': [], 'metadata': {'samplingMetadatas': [{'range':'30d'}]}, 'propertyQuota': {'tokensPerHour': 100}}
        with patch('src.integrations.requests.post', return_value=MockResponse()) as request:
            search_console('sc-domain:example.com','token','2026-01-01','2026-01-02', ['query'], 100, [{'filters':[]}], 'web', 'auto', 20)
            payload=request.call_args.kwargs['json']
            self.assertEqual(payload['startRow'],20); self.assertEqual(payload['type'],'web'); self.assertIn('dimensionFilterGroups',payload)
        from src.integrations import ga4_report
        with patch('src.integrations.requests.post', return_value=MockResponse()) as request:
            report=ga4_report('123','token','2026-01-01','2026-01-02',['date'],['sessions'],metric_filter={'filter':{}},order_bys=[{'metric':{'metric_name':'sessions'}}],limit=25,offset=5,keep_empty_rows=True,return_property_quota=True)
            payload=request.call_args.kwargs['json']
            self.assertEqual(payload['limit'],25); self.assertEqual(payload['offset'],5); self.assertTrue(payload['keepEmptyRows']); self.assertTrue(report['_request_metadata']['property_quota_requested']); self.assertFalse(report['_request_metadata']['sampling_unknown']); self.assertEqual(report['_request_metadata']['property_quota']['tokensPerHour'],100)
        from src.integrations import bing_webmaster_operation
        with self.assertRaises(ValueError): bing_webmaster_operation('unknown','http://127.0.0.1:1','x')

        received = {}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received['authorization'] = self.headers.get('Authorization')
                length = int(self.headers.get('Content-Length', 0))
                received['payload'] = json.loads(self.rfile.read(length))
                body = json.dumps({'ok': True, 'adapter': 'mock'}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *_args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            response = call_connector('gsc', 'http://127.0.0.1:%d/report' % server.server_port,
                                      {'site': 'https://example.test'}, 'secret')
            self.assertTrue(response['ok']); self.assertEqual(received['authorization'], 'Bearer secret')
            self.assertEqual(received['payload']['site'], 'https://example.test')
        finally:
            server.shutdown(); thread.join(timeout=2); server.server_close()

    def test_professional_capability_catalog(self):
        from src.professional_tools import SEO_TOOL_CATALOG, capability_catalog, capability_audit
        capabilities=capability_catalog()
        self.assertIn('autonomous-agent', SEO_TOOL_CATALOG)
        self.assertEqual(len(capabilities), len(SEO_TOOL_CATALOG))
        self.assertTrue(any(x['tool']=='gsc-report' and x['mode']=='external-adapter' for x in capabilities))
        audit=capability_audit()
        self.assertTrue(audit['all_catalogued'])
        self.assertTrue(all(area['complete'] for area in audit['areas']))
        self.assertIn('graphql-api', SEO_TOOL_CATALOG)
        self.assertIn('immutable-audit', SEO_TOOL_CATALOG)

    def test_mcp_capability_audit(self):
        original_argv = sys.argv[:]
        original_local = os.environ.get('LOCAL_MODE')
        sys.argv = ['librecrawl-test']
        os.environ['LOCAL_MODE'] = 'true'
        try:
            from main import app
        finally:
            sys.argv = original_argv
            if original_local is None: os.environ.pop('LOCAL_MODE', None)
            else: os.environ['LOCAL_MODE'] = original_local
        client = app.test_client()
        response = client.post('/api/mcp', json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'seo_capability_audit','arguments':{}}})
        self.assertEqual(response.status_code, 200)
        self.assertIn('all_catalogued', response.get_json()['result']['content'][0]['text'])

    def test_nextgen_priority_tools(self):
        from src.nextgen_priority import experiment_platform, conversion_rank_tracker, algorithm_forensics, regression_gate, remediation_plan, content_roi, competitor_intelligence, citation_gap
        self.assertTrue(experiment_platform('title', [{'conversions':10}], {'B':[{'conversions':20}]})['variants'][0]['winner'])
        self.assertEqual(conversion_rank_tracker([{'position':2,'clicks':10,'conversions':2}])[0]['conversion_rate'],.2)
        self.assertEqual(algorithm_forensics([{'name':'update'}],[{'url':'/a','before_position':2,'after_position':8}])['affected_pages'][0]['direction'],'loss')
        self.assertFalse(regression_gate({'errors':0,'titles':10},{'errors':1,'titles':9})['passed'])
        self.assertTrue(remediation_plan([{'url':'/a','issue':'title','patch':{'title':'New'}}])['plans'][0]['rollback_available'])
        self.assertGreater(content_roi([{'revenue':100,'cost':10}])[0]['roi'],0)
        self.assertEqual(competitor_intelligence([], [{'url':'/new'}])[0]['event'],'new_content')
        self.assertEqual(citation_gap(['q'],['brand.example'],{'q':['other.example']})[0]['citation_gap'],['brand.example'])

    def test_nextgen_advanced_tools(self):
        from src.nextgen_advanced import serp_screenshot_archive, intent_drift_detector, large_migration_rehearsal, knowledge_graph_conflicts, crawl_budget_optimizer
        self.assertTrue(serp_screenshot_archive([{'id':'a','html':'one'},{'id':'b','html':'two'}])['diffs'][0]['changed'])
        self.assertEqual(intent_drift_detector([{'keyword':'seo','intent':'info'}],[{'keyword':'seo','intent':'commercial'}])['changed'],1)
        self.assertFalse(large_migration_rehearsal([{'url':'/a'}],[],{})['passed'])
        self.assertFalse(knowledge_graph_conflicts([{'url':'/a','schema_entities':['A'],'content_entities':['B']}])['passed'])
        self.assertEqual(len(crawl_budget_optimizer([{'url':'/a','priority':2}],1)['queue']),1)

    def test_nextgen_operations(self):
        from src.nextgen_operations import digital_pr_opportunities, seo_security_scan, multilingual_quality, marketplace_monitor, incident_response, seo_copilot_memory
        self.assertTrue(digital_pr_opportunities([{'authority':80,'relevance':90,'audience':10000,'cost':1}])['prospects'][0]['recommended'])
        self.assertFalse(seo_security_scan([{'url':'/a','malware':True}])['passed'])
        self.assertLess(multilingual_quality([{'language':'it','content_text':'x'}], ['it','en'])[0]['quality_score'],100)
        self.assertFalse(marketplace_monitor([{'id':'p','amazon':{}}])['passed'])
        self.assertEqual(incident_response([{'severity':'critical','count':1}])['active'],1)
        self.assertEqual(seo_copilot_memory([{'approved':False,'decision':'x'},{'approved':True,'decision':'redirect'}])['count'],1)

    def test_frontier_seo(self):
        from src.frontier_seo import causal_impact_multifactor, realtime_digital_twin, proprietary_knowledge_graph, revenue_at_risk_incidents, seo_canary_deploy, ai_factuality_check, content_provenance, backlink_risk_disavow, self_hosted_data_lake, seo_feature_flags, googlebot_behavior_profiler, content_quality_benchmark, internal_link_optimizer, lighthouse_regression, rum_multi_country, privacy_attribution, capacity_planner, multi_brand_governance, evidence_vault
        self.assertGreater(causal_impact_multifactor([10,20,30,40],[10,15,20,25],{'paid':1})['causal_effect'],0)
        self.assertTrue(realtime_digital_twin([{'url':'/a','title':'old'}],[{'url':'/a','title':'new'}])['rollback_available'])
        graph=proprietary_knowledge_graph([{'url':'/a','keywords':['seo'],'entities':['Search'],'authors':['A'],'conversion_value':10}])
        self.assertGreaterEqual(graph['node_count'],5); self.assertEqual(len(graph['graph_hash']),64)
        self.assertGreater(revenue_at_risk_incidents([{'revenue':1000,'probability':.5}])[0]['revenue_at_risk'],0)
        self.assertEqual(seo_canary_deploy([],{'errors':0,'conversions':10},{'errors':1,'conversions':10})['status'],'rollback')
        self.assertTrue(ai_factuality_check([{'claims':['known']}],['known'])[0]['factuality_score']==1)
        self.assertFalse(content_provenance([{'origin':'ai'}])[0]['publishable'])
        self.assertTrue(backlink_risk_disavow([{'domain':'bad.test','spam_score':100}])['disavow_domains'])
        self.assertEqual(self_hosted_data_lake([{'dimension':'IT','value':3}],dimension='dimension')['aggregates']['IT'],3)
        self.assertEqual(seo_feature_flags([{'url':'/a','template':'article'}],{'x':{'templates':['article'],'changes':{'title':'X'}}})[0]['enabled_flags'],['x'])
        self.assertEqual(googlebot_behavior_profiler([{'url':'https://x.test/a','status_code':200}])[0]['visits'],1)
        self.assertEqual(content_quality_benchmark([{'content_text':'word '*500,'author':'A'}])[0]['benchmark_status'],'above')
        self.assertTrue(internal_link_optimizer([{'url':'/a'}],[])[0]['priority'])
        self.assertFalse(lighthouse_regression({'performance':100},{'performance':80})['passed'])
        cwv_gate=lighthouse_regression({}, {'performance':95,'lcp':3.2}, {'cwv':{'lcp':2.5}})
        self.assertFalse(cwv_gate['passed']); self.assertEqual(cwv_gate['metrics'][0]['metric'],'lcp')
        self.assertEqual(rum_multi_country([{'country':'IT','lcp':2}])[0]['samples'],1)
        self.assertEqual(privacy_attribution([{'channels':['seo'],'revenue':10}])[0]['attributed_revenue'],10)
        self.assertTrue(capacity_planner([{'effort_days':2}],1,1)['overloaded'])
        self.assertTrue(multi_brand_governance([{'brand':'A'}],{'A':'owner'})['items'][0]['permission_checked'])
        self.assertTrue(evidence_vault([{'event':'x'}])['chain_of_custody'])

    def test_research_enterprise_tools(self):
        from src.research_enterprise import capability_matrix, page_inspect_history, portfolio_metrics, ai_bot_analytics, ai_visibility_report, report_task, report_task_status, data_quality_report, workspace_audit, patch_automation, patch_transition, patch_apply_local, patch_rollback_local, portfolio_dashboard
        self.assertGreaterEqual(capability_matrix()['count'],10); self.assertTrue(capability_matrix()['all_available'])
        self.assertTrue(page_inspect_history([{'url':'/a','source_html':'a','rendered_html':'b'}])['snapshots'][0]['render_diff'])
        self.assertEqual(portfolio_metrics([{'domain':'a','revenue':10},{'domain':'b','revenue':20}])['totals']['revenue'],30)
        self.assertEqual(ai_bot_analytics([{'bot':'GPTBot','status_code':200}])[0]['requests'],1)
        bot_report=ai_bot_analytics([{'user_agent':'Mozilla GPTBot','status_code':404,'path':'/guide','bytes':20}])[0]
        self.assertEqual(bot_report['bot'],'GPTBot'); self.assertEqual(bot_report['status_codes']['404'],1); self.assertEqual(bot_report['paths'],['/guide'])
        visibility=ai_visibility_report([{'prompt':'seo','answer':True,'citations':[{'url':'https://example.com/a'}]}],'example.com')
        self.assertEqual(visibility['summary']['owned_prompts'],1); self.assertEqual(visibility['summary']['visibility_rate'],1.0)
        task=report_task({'x':1}); self.assertEqual(task['status'],'completed'); self.assertEqual(report_task_status(task['task_id'])['result']['x'],1)
        self.assertEqual(data_quality_report([{'url':'/a'}],['title'])['missing_values'],1)
        self.assertTrue(workspace_audit([{'action':'read'}])[0]['allowed'])
        self.assertFalse(patch_automation([{'url':'/a','patch':{'title':'x'}}])['plans'][0]['executed'])
        self.assertIn('portfolio', portfolio_dashboard([{'domain':'a','revenue':1}]))
        plan=patch_automation([{'url':'/a','patch':{'title':'x'}}])['plans']; self.assertEqual(patch_transition(plan,True)['status'],'approved'); self.assertEqual(patch_transition(plan,rollback=True)['status'],'rollback_ready')
        applied=patch_apply_local([{'url':'/a','title':'old'}],plan,True); self.assertEqual(applied['rows'][0]['title'],'x'); self.assertFalse(applied['external_deploy'])
        restored=patch_rollback_local(applied['rows'],applied['changes'],True); self.assertEqual(restored['rows'][0]['title'],'old'); self.assertTrue(restored['rolled_back'])

    def test_enterprise_next_tools(self):
        from src.enterprise_next_tools import enterprise_next_capabilities, parse_log_lines, log_analyzer, rum_compare, crux_query, migration_assistant, security_scan, content_governance, serp_volatility, brand_monitor, rich_results_bulk, crawl_replay, warehouse_export, warehouse_query, product_intelligence, prioritize
        self.assertEqual(enterprise_next_capabilities()['count'],12)
        parsed=parse_log_lines(['127.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "GET /products/a HTTP/1.1" 500 120 "-" "Googlebot"'])
        self.assertEqual(parsed[0]['bot'],'Googlebot'); self.assertEqual(parsed[0]['status'],500)
        self.assertEqual(log_analyzer([{'url':'/a','status':500,'bot':'Googlebot'}])['errors_5xx'] if False else log_analyzer([{'url':'/a','status':500,'bot':'Googlebot'}])['directories'][0]['errors_5xx'],1)
        self.assertEqual(rum_compare([{'country':'IT','device':'mobile','template':'product','lcp':2}])['sample_count'],1)
        class CruxResponse:
            def raise_for_status(self): pass
            def json(self): return {'record':{'metrics':{}}}
        with patch('src.enterprise_next_tools.requests.post', return_value=CruxResponse()) as request:
            self.assertEqual(crux_query(origin='https://example.com',api_key='key')[' _source'.strip()],'CrUX API'); self.assertEqual(request.call_args.kwargs['json']['origin'],'https://example.com')
        self.assertTrue(migration_assistant([{'url':'/a'}],[],{'/a':'/new'})['passed'])
        self.assertFalse(security_scan([{'url':'/a','source_html':'eval("x")'}])['passed'])
        self.assertTrue(any(x['type']=='possible_cloaking' for x in security_scan([{'url':'/c','source_html':'a','source_text':'short','rendered_text':'a '*20}])['findings']))
        self.assertEqual(content_governance([{'url':'/a','owner':'seo','title':'new'}],previous=[{'url':'/a','title':'old'}])['changed_pages'],1)
        self.assertTrue(serp_volatility([{'keyword':'x','position':1,'date':'2026-01-01'},{'keyword':'x','position':10,'date':'2026-01-02'}],['2026-01-02'])['rows'][0]['update_correlation'])
        brand=brand_monitor([{'brand':'X','linked':False,'branded':True,'knowledge_panel':True}]); self.assertEqual(brand['unlinked_mentions'][0]['brand'],'X'); self.assertEqual(brand['knowledge_panel_observations'],1)
        self.assertEqual(rich_results_bulk([{'url':'/a','json_ld':[{'@type':'Product','name':'P','offers':{'price':'1'}}]}])['eligible'],1)
        replay=crawl_replay([{'url':'/a','source_hash':'a','dom_hash':'b','network':[{}],'console_errors':[{}]}]); self.assertTrue(replay['hydration_mismatches']); self.assertEqual(replay['network_requests'],1)
        self.assertIn('url',warehouse_export([{'url':'/a'}],'csv'))
        self.assertEqual(warehouse_query([{'url':'/a','status':200},{'url':'/b','status':404}],"SELECT url FROM rows WHERE status = 404")['rows'][0]['url'],'/b')
        product=product_intelligence([{'url':'/p','stock':0},{'url':'/q','stock':1,'indexable':False,'id':'q'}],[{'id':'q','url':'/q','availability':'in_stock'},{'id':'q','url':'/dup'}]); self.assertEqual(product['stockouts'],1); self.assertTrue(any(x['type']=='in_stock_not_indexable' for x in product['findings'])); self.assertFalse(product['feed_consistent'])
        priority=prioritize([{'url':'/a','impact':10,'difficulty':1,'template':'product'}]); self.assertEqual(priority['issues'][0]['url'],'/a'); self.assertEqual(priority['templates'][0]['template'],'product')
        from src.priority_tools import cron_next, resource_audit, spa_detection, duplicate_fingerprint
        self.assertTrue(cron_next('0 9 * * 0','Europe/Rome',datetime.fromisoformat('2026-01-05T10:00:00+01:00')).startswith('2026-01-12T09:00'))
        self.assertEqual(resource_audit([{'resources':[{'type':'script','size':100,'status_code':200},{'type':'image','bytes':20,'status_code':404}]}])['total_errors'],1)
        self.assertTrue(spa_detection({'url':'/','source_html':'<div id="root"></div><script src="app.js"></script><script src="vendor.js"></script>'})['spa_detected'])
        self.assertEqual(len(duplicate_fingerprint('same text')['md5']),32); self.assertEqual(len(duplicate_fingerprint('same text',True)['simhash']),16)
    def test_advanced_directives_and_resources(self):
        html = '''<html><head>
        <link rel="next" href="/page/2"><link rel="prev" href="/page/1">
        <link rel="amphtml" href="/amp"><link rel="alternate" media="only screen and (max-width: 640px)" href="/mobile"><meta http-equiv="refresh" content="5; url=/new">
        </head><body><img srcset="a.jpg 1x, b.jpg 2x"><script src="app.js"></script></body></html>'''
        result = {}
        extractor = SEOExtractor()
        soup = BeautifulSoup(html, 'html.parser')
        extractor.extract_advanced_directives(soup, 'https://example.test/page', result)
        extractor.extract_resources(soup, 'https://example.test/page', result)
        self.assertEqual(result['pagination']['next'], 'https://example.test/page/2')
        self.assertEqual(result['amp_url'], 'https://example.test/amp')
        self.assertEqual(result['mobile_alternate'], 'https://example.test/mobile')
        self.assertIn('/new', result['meta_refresh'])
        self.assertEqual(len(result['srcset']), 2)
        self.assertTrue(any(item['type'] == 'script' for item in result['resources']))
        extractor.extract_accessibility(soup, result)
        self.assertIn('score', result['accessibility'])
        self.assertTrue(any(item['rule'] == 'skip-link-missing' for item in result['accessibility']['findings']))
        table_result = {'url':'/table'}
        SEOExtractor.extract_accessibility(BeautifulSoup('<html lang="en"><table><tr><td>x</td></tr></table><a href="#main">Skip</a></html>', 'html.parser'), table_result)
        self.assertTrue(any(item['rule'] == 'table-header-missing' for item in table_result['accessibility']['findings']))
        extractor.extract_custom_search(html, result, [{'name': 'amp', 'type': 'text', 'query': 'amphtml'}])
        self.assertTrue(result['custom_search']['amp']['matched'])

    def test_limits_and_seo_utilities(self):
        manager = LinkManager('example.test')
        soup = BeautifulSoup('<a href="/1">1</a><a href="/2">2</a>', 'html.parser')
        manager.extract_links(soup, 'https://example.test/', 1, lambda _: True, max_links=1)
        self.assertEqual(len(manager.discovered_urls), 1)
        self.assertFalse(test_robots('User-agent: *\nDisallow: /private/', 'https://example.test/private/page', 'LibreCrawl')['allowed'])
        self.assertIn('<loc>https://example.test/a</loc>', generate_sitemap([{'url': 'https://example.test/a'}]))
        self.assertIn('<sitemapindex', generate_sitemap_index(['https://example.test/sitemap-1.xml']))
        self.assertEqual(apply_cdn('https://example.test/a', 'cdn.example.test'), 'https://cdn.example.test/a')
        self.assertEqual(len(segment_urls([{'status_code': 200}, {'status_code': 404}], 'status_code:200')), 1)
        crawler = WebCrawler()
        crawler.update_config({'max_redirects': 2, 'enable_proxy': True, 'proxy_url': 'http://proxy.test:8080', 'proxy_username': 'user', 'proxy_password': 'pass', 'proxy_no_proxy': 'localhost', 'trusted_certificates': False})
        self.assertEqual(crawler.session.max_redirects, 2)
        self.assertFalse(crawler.session.verify)
        self.assertIn('proxy.test:8080', crawler.session.proxies['http'])

    def test_advanced_data_persistence(self):
        init_crawl_tables()
        url = 'https://parity.test/'
        self.assertTrue(save_url_batch(4, [{
            'url': url, 'status_code': 200, 'pdf_pages': 3,
            'http_headers': {'content-type': 'application/pdf'},
            'security': {'hsts': True}, 'media_type': 'pdf',
            'pagination': {'next': 'https://parity.test/2'},
            'source_html': '<html>source</html>', 'rendered_html': '<html>rendered</html>',
            'extracted_text': 'enterprise text', 'snapshot_type': 'source',
            'snapshot_captured_at': '2026-01-01T00:00:00Z'
        }]))
        rows = [row for row in load_crawled_urls(4) if row['url'] == url]
        self.assertTrue(rows)
        self.assertEqual(rows[-1]['pdf_pages'], 3)
        self.assertEqual(rows[-1]['pagination']['next'], 'https://parity.test/2')
        self.assertEqual(rows[-1]['source_html'], '<html>source</html>')
        self.assertEqual(rows[-1]['extracted_text'], 'enterprise text')
        self.assertTrue(rows[-1]['security']['hsts'])

    def test_content_and_architecture_analysis(self):
        soup = BeautifulSoup('<main>Useful SEO content. Useful SEO content.</main>', 'html.parser')
        analysis = analyze_content(soup)
        self.assertEqual(analysis['content_area'], 'main')
        self.assertIn('readability', analysis)
        self.assertTrue(analysis['n_grams']['bigrams'])
        selected = analyze_content(BeautifulSoup('<div class="copy">Selected words.</div><footer>Ignore.</footer>', 'html.parser'), '.copy')
        self.assertEqual(selected['content_area'], 'div')
        self.assertIn('Selected', selected['content_text'])
        old = [{'url': 'https://x.test/a', 'title': 'Old', 'status_code': 200}]
        new = [{'url': 'https://x.test/a', 'title': 'New', 'status_code': 200}, {'url': 'https://x.test/b', 'depth': 1}]
        changes = detect_changes(old, new)
        self.assertEqual({item['type'] for item in changes}, {'changed', 'added'})
        self.assertEqual(len(orphan_pages(new, [{'source_url': 'https://x.test/', 'target_url': 'https://x.test/a'}])), 1)
        results = semantic_search([{'url': 'https://x.test/a', 'title': 'SEO audit', 'content_text': 'technical SEO'}], 'SEO')
        self.assertTrue(results and results[0]['url'].endswith('/a'))
        nested = semantic_search([{'url': 'https://x.test/nested', 'content_analysis': {'content_text': 'unique lighthouse phrase'}}], 'lighthouse phrase')
        self.assertTrue(nested and nested[0]['url'].endswith('/nested'))
        self.assertFalse(embedding_search([], 'SEO', '')['success'])
        metrics = calculate_link_metrics(new, [{'source_url': 'https://x.test/a', 'target_url': 'https://x.test/b'}])
        self.assertEqual(metrics[0]['inlinks'], 1)
        with self.assertRaises(ValueError):
            backlink_metrics('', '', 'https://x.test')

    def test_screaming_frog_parity_panels_and_custom_rules(self):
        from src.parity_tools import page_panels, custom_extract, custom_search, link_positions, html_validation
        row = {'url': 'https://x.test/a', 'status_code': 200, 'title': 'Page',
               'meta_description': 'Description',
               'source_html': '<html><head><title>Page</title></head><body><h1>Main</h1><a href="/b">Link</a><img src="/a.jpg" alt="A"></body></html>',
               'http_headers': {'content-type': 'text/html'}}
        panels = page_panels(row)
        self.assertEqual(panels['serp_snippet']['title'], 'Page')
        self.assertEqual(panels['outlinks'][0]['href'], '/b')
        self.assertEqual(panels['images'][0]['alt'], 'A')
        self.assertTrue(custom_extract(row, [{'name': 'headings', 'selector': 'h1'}])['extractions']['headings'])
        self.assertTrue(custom_search(row, [{'name': 'main', 'term': 'Main'}])['searches'][0]['found'])
        self.assertEqual(link_positions(row)['links'][0]['href'], '/b')
        self.assertTrue(html_validation(row)['valid'])
        self.assertFalse(html_validation({'url': '/broken', 'source_html': '<html><body>'})['valid'])
        self.assertIn('lighthouse', panels)
        self.assertIn('spelling_grammar', panels)

    def test_schedule_execution_is_async_and_persists_status(self):
        from src.scheduler_service import execute_schedule
        with tempfile.TemporaryDirectory() as directory, patch('src.scheduler_service.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            run.return_value.stderr = ''
            result = execute_schedule({'id': 999991, 'name': 'test', 'url': 'https://example.com', 'mode': 'spider', 'recipients': '[]', 'settings_snapshot': '{}'}, directory)
            self.assertTrue(result['accepted'])
            for _ in range(20):
                status_path = result['output'] + '.status.json'
                if os.path.exists(status_path):
                    break
                import time
                time.sleep(0.01)
            self.assertTrue(os.path.exists(result['output'] + '.status.json'))

    def test_pagespeed_adapter_and_update_checksum(self):
        from src.integrations import pagespeed_insights
        fake_response = type('Response', (), {'raise_for_status': lambda self: None, 'json': lambda self: {'lighthouseResult': {'categories': {}}}})()
        with patch('src.integrations.requests.get', return_value=fake_response) as request:
            result = pagespeed_insights('https://example.com', strategy='desktop', categories=['seo'])
            self.assertEqual(result['_request_scope']['strategy'], 'desktop')
            self.assertIn('strategy', request.call_args.kwargs['params'])
        from src.update_service import download_update
        with tempfile.TemporaryDirectory() as directory:
            archive = os.path.join(directory, 'update.zip')
            with open(archive, 'wb') as handle:
                handle.write(b'update')
            import hashlib
            manifest = {'url': 'https://updates.test/update.zip', 'version': '1.1.0', 'sha256': hashlib.sha256(b'update').hexdigest()}
            with patch('src.update_service.urllib.request.urlopen') as opener:
                context = opener.return_value.__enter__.return_value
                context.read.side_effect = [b'update', b'']
                downloaded = download_update(manifest, directory)
            self.assertTrue(downloaded['verified'])

    def test_update_rollback_restores_backup(self):
        from src.update_service import rollback_update
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.join(directory, 'app')
            backup = root + '.backup'
            os.makedirs(root)
            os.makedirs(backup)
            with open(os.path.join(root, 'version.txt'), 'w') as handle: handle.write('new')
            with open(os.path.join(backup, 'version.txt'), 'w') as handle: handle.write('old')
            result = rollback_update(root)
            self.assertTrue(result['rolled_back'])
            with open(os.path.join(root, 'version.txt')) as handle: self.assertEqual(handle.read(), 'old')

    def test_report_contract_exposes_tab_counts(self):
        from src.parity_tools import page_panels
        self.assertIn('serp_snippet', page_panels({'url': 'https://x.test', 'title': 'X'}))

    def test_scheduler_timezone_and_due_polling(self):
        from src.crawl_db import create_schedule, list_schedules
        from src.scheduler_service import run_due_schedules_once
        schedule_id = create_schedule(1, 'due-test', 'https://example.com', interval_seconds=3600, timezone='Europe/Malta')
        schedule = next(item for item in list_schedules(1) if item['id'] == schedule_id)
        self.assertEqual(schedule['timezone'], 'Europe/Malta')
        with patch('src.scheduler_service.execute_schedule', side_effect=lambda schedule, output_dir: {'schedule_id': schedule['id'], 'accepted': True}) as execute:
            result = run_due_schedules_once('reports-test')
            self.assertTrue(any(item.get('schedule_id') == schedule_id for item in result))
            execute.assert_called()

    def test_auto_update_bootstrap_check_mode(self):
        with patch.object(sys, 'argv', ['main.py', '--local']), patch.dict(os.environ, {'LIBRECRAWL_UPDATE_MANIFEST_URL': 'https://updates.test/manifest.json', 'LIBRECRAWL_AUTO_UPDATE': 'check'}), \
             patch('src.update_service.check_update', return_value={'current_version': '1.0.0', 'available_version': '1.0.0', 'update_available': False}):
            import main as application
            application.maybe_auto_update()

    def test_summary_storage_drops_heavy_render_payloads(self):
        crawler = WebCrawler()
        crawler.db_save_enabled = True
        crawler.crawl_id = 987654
        crawler.config['storage_mode'] = 'summary'
        crawler.unsaved_urls = [{'url': 'https://x.test', 'title': 'X', 'source_html': '<html>', 'rendered_html': '<html>', 'extracted_text': 'text', 'render_diagnostics': {'network': []}, 'status_code': 200}]
        with patch('src.crawl_db.save_url_batch', return_value=True) as save_urls, patch('src.crawl_db.update_crawl_stats', return_value=True):
            crawler._save_batch_to_db()
            saved = save_urls.call_args.args[1][0]
            self.assertEqual(saved['title'], 'X')
            self.assertNotIn('source_html', saved)
            self.assertNotIn('rendered_html', saved)

    def test_advanced_spider_preferences_are_applied(self):
        crawler = WebCrawler()
        from src.core.link_manager import LinkManager
        crawler.link_manager = LinkManager('example.com')
        crawler.base_domain = 'example.com'
        crawler.base_url = 'https://example.com/'
        crawler.config.update({'crawl_fragments': False, 'follow_canonical': True, 'follow_meta_refresh': True})
        self.assertFalse(crawler._should_crawl_url('https://example.com/page#section'))
        crawler.config['crawl_fragments'] = True
        self.assertTrue(crawler._should_crawl_url('https://example.com/page#section'))

    def test_redirect_chain_preference_reaches_crawler_config(self):
        from src.settings_manager import SettingsManager
        manager = SettingsManager(user_id=1, tier='admin')
        settings = manager.get_settings()
        settings['followRedirects'] = True
        settings['followRedirectChains'] = False
        manager.current_settings = settings
        self.assertFalse(manager.get_crawler_config()['follow_redirects'])

    def test_parity_catalog_is_machine_readable(self):
        from src.parity_catalog import parity_catalog
        catalog = parity_catalog()
        self.assertGreaterEqual(catalog['feature_count'], 20)
        self.assertEqual(catalog['catalog']['integrations']['pagespeed'], '/api/integrations/pagespeed')

    def test_cookie_storage_round_trip(self):
        crawler = WebCrawler()
        crawler.crawl_id = 123456
        crawler.config['cookie_storage'] = True
        crawler.session.cookies.set('consent', 'yes', domain='example.test', path='/')
        with tempfile.TemporaryDirectory() as directory:
            old = os.getcwd()
            try:
                os.chdir(directory)
                crawler._save_cookie_storage()
                crawler.session.cookies.clear()
                crawler._load_cookie_storage()
                self.assertEqual(crawler.session.cookies.get('consent', domain='example.test'), 'yes')
            finally:
                os.chdir(old)

    def test_ui_parity_contract(self):
        template = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web', 'templates', 'index.html')
        with open(template, encoding='utf-8') as source:
            html = source.read()
        for label in ('Internal', 'External', 'Security', 'Response Codes', 'Page Titles', 'Meta Description', 'Hreflang', 'Structured Data', 'Sitemaps', 'Accessibility', 'Validation', 'Search Console', 'Change Detection'):
            self.assertIn(label, html)
        for element_id in ('projectImportFile', 'historicalExportDataset', 'scheduleName', 'scheduleTimezone', 'pagespeedUrl', 'cookieStorage', 'spiderView', 'spiderDatasetCrawlId', 'spiderDatasetTable', 'reportAnalysisCrawlId', 'visualizationCrawlId', 'ignoreNonIndexableDuplicates', 'followCanonical', 'retry5xxAttempts', 'enableHtmlValidation', 'updateManifestUrl', 'applicationUpdateResult'):
            self.assertIn(f'id="{element_id}"', html)
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web', 'static', 'js', 'app.js'), encoding='utf-8') as source:
            app_js = source.read()
        self.assertIn('renderDetailPanel', app_js)
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web', 'static', 'css', 'styles.css'), encoding='utf-8') as source:
            styles = source.read()
        self.assertIn('.spider-dataset-toolbar', styles)
        for label in ('Page Titles', 'Meta Description', 'Headings', 'Canonicals', 'Directives', 'Hreflang', 'Structured Data'):
            self.assertIn(label, html)
        for value in ('pagination', 'amp', 'sitemaps', 'mobile', 'analytics', 'search-console', 'link-metrics', 'ai', 'changes'):
            self.assertIn(f'value="{value}"', html)
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'main.py'), encoding='utf-8') as source:
            self.assertIn('unsupported dataset', source.read())

    def test_password_inputs_have_form_association(self):
        template = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'web', 'templates', 'index.html')
        with open(template, encoding='utf-8') as source:
            html = source.read()
        import re
        for field in re.findall(r'<input[^>]+type="password"[^>]*>', html):
            self.assertIn('form="credentialForm"', field)


if __name__ == '__main__':
    unittest.main()
