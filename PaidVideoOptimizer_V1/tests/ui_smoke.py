"""Run after starting local server: python tests/ui_smoke.py. Needs Playwright + Chromium."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import json, os, shutil, argparse
parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:8765')
parser.add_argument('--out',default=str(Path(__file__).resolve().parents[1]/'test_artifacts'))
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
out=Path(args.out);out.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1600,'height':1050},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 # Exercise the served HTML, scripts, storage and same-origin HTTP boundary.
 page.goto(args.url,wait_until='networkidle')
 page.locator('button[data-action="view"][data-value="imports"]').first.click()
 page.wait_for_selector('[data-action="load-real"]')
 page.locator('[data-action="load-real"]').first.click()
 page.wait_for_selector('.top-card',timeout=20000)
 page.evaluate("() => {const t=document.getElementById('toast');if(t)t.style.display='none'}")
 page.screenshot(path=str(out/'01_真实历史榜.png'),full_page=True)
 print('REAL CARDS',page.locator('.top-card').count())
 # Refresh must restore the same snapshot and exposure tier, without recalculation.
 saved_export=page.locator('a[href^="/api/exports/"]').first.get_attribute('href')
 saved_tier=page.locator('#exposure-tier').input_value()
 page.reload(wait_until='networkidle')
 page.wait_for_selector('.top-card')
 assert page.locator('a[href^="/api/exports/"]').first.get_attribute('href')==saved_export
 assert page.locator('#exposure-tier').input_value()==saved_tier
 assert '已恢复上次查看的排名' in page.locator('body').inner_text()
 page.locator('button[data-action="view"][data-value="materials"]').first.click()
 page.wait_for_selector('tbody tr');page.screenshot(path=str(out/'02_全量指标.png'),full_page=True)
 page.locator('[data-action="detail"]').first.click()
 page.wait_for_selector('.detail-metrics');page.screenshot(path=str(out/'03_指标解释.png'),full_page=True)
 page.locator('[data-action="close"]').click()
 page.locator('[data-action="demo"]').first.click()
 page.wait_for_function("document.querySelector('.notice')?.textContent?.includes('教学模拟')",timeout=15000)
 page.wait_for_selector('[data-action="propose"]');page.locator('[data-action="propose"]').click()
 page.wait_for_selector('.proposal');page.evaluate("() => {const t=document.getElementById('toast');if(t)t.style.display='none'}");page.screenshot(path=str(out/'04_追投建议.png'),full_page=True)
 page.on('dialog',lambda d:d.accept())
 page.locator('[data-action="approve"]').first.click()
 page.wait_for_selector('[data-action="execute-modal"]')
 page.locator('[data-action="execute-modal"]').first.click()
 page.locator('input[name="confirm_platform_done"]').check()
 page.locator('form[data-form="execute"] button.primary').click()
 page.wait_for_selector('[data-action="review-modal"]')
 page.locator('[data-action="review-modal"]').first.click()
 page.select_option('select[name="maturity"]','matured')
 page.fill('input[name="cohort_spend"]','100');page.fill('input[name="cohort_net_gmv"]','700');page.fill('input[name="net_orders"]','7')
 # First proposal is bid action: no new budget reservation.
 page.fill('input[name="settled_spend"]','0')
 page.check('input[name="passed"]');page.check('input[name="reservation_closed"]')
 page.fill('input[name="note"]','浏览器端到端教学复核；没有实际广告动作。')
 page.locator('form[data-form="review"] button.primary').click()
 page.wait_for_function("!document.querySelector('.modal')")
 page.screenshot(path=str(out/'05_执行复核.png'),full_page=True)
 # Settings and file upload preview are functional, not static mockups.
 page.locator('button[data-action="view"][data-value="imports"]').first.click()
 page.locator('#uploads').set_input_files(str(ROOT/'examples/product_30d.csv'))
 page.wait_for_selector('form[data-form="confirm-import"]',timeout=15000)
 page.screenshot(path=str(out/'06_导入确认.png'),full_page=True)
 page.locator('button[data-action="view"][data-value="settings"]').first.click()
 page.wait_for_selector('form[data-form="settings"]')
 page.screenshot(path=str(out/'07_策略预算.png'),full_page=True)
 page.set_viewport_size({'width':780,'height':1100})
 page.locator('button[data-action="view"][data-value="dashboard"]').first.click()
 page.screenshot(path=str(out/'08_窄屏布局.png'),full_page=True)
 # Chengfang uses frozen, plan-scoped diagnosis instead of independent boost actions.
 api=p.request.new_context(base_url=args.url)
 workspace=api.post('/api/workspaces',data={'name':'浏览器成方诊断'}).json()
 config=workspace['config'];config['delivery_mode']='chengfang'
 assert api.put(f"/api/workspaces/{workspace['id']}/config",data=config).ok
 context={'plan_id':'smoke-plan','path':'live','status':'active','started_at':'2026-09-01T08:00:00+08:00',
          'marketing_roi_target':2.5,'base_delivery':True,'star_select':False,'creator_marketing':False,
          'creator_commission_bid':False,'basis_note':'浏览器烟测冻结口径'}
 assert api.put(f"/api/workspaces/{workspace['id']}/chengfang/context",data=context).ok
 labels={'content_type':'口播','hook':'三秒开场','value_proposition':'省心','person':'主播','scene':'直播间','price_expression':'限时价','duration_band':'15-30秒'}
 for creative in ('cf-a','cf-b'):
  assert api.put(f"/api/workspaces/{workspace['id']}/chengfang/plans/smoke-plan/materials/{creative}",data={'path':'live','labels':labels}).ok
 def chengfang_import(start,end,orders):
  csv=('素材ID,整体消耗,净成交金额,净成交订单数,计划ID,营销消耗,曝光量\n'
       f'cf-a,150,600,{orders},smoke-plan,150,3000\ncf-b,150,600,{orders},smoke-plan,150,3000\n').encode()
  preview=api.post('/api/imports/preview',multipart={'workspace_id':workspace['id'],'file':{'name':f'{start}.csv','mimeType':'text/csv','buffer':csv}}).json()
  body={'plan_id':'smoke-plan','path':'live','partition':'chengfang','period_start':start,'period_end':end,
        'scope':'浏览器成方诊断范围','scope_confirmed':True,'cost_basis':'marketing_cost','cost_grain':'material_attributable','plan_marketing_cost':300}
  response=api.post(f"/api/imports/{preview['id']}/confirm",data=body)
  assert response.ok,response.text()
  return response.json()
 prior=chengfang_import('2026-09-01','2026-09-07',2)
 current=chengfang_import('2026-09-08','2026-09-14',4)
 # A plan/context mismatch is rejected at the browser's same-origin API boundary.
 blocked=api.post('/api/chengfang/diagnosis-runs',data={'workspace_id':workspace['id'],'plan_id':'wrong-plan','path':'live','current_import_id':current['id']})
 assert blocked.status==400
 page.set_viewport_size({'width':1600,'height':1050})
 page.locator('button[data-action="refresh"]').click()
 page.wait_for_function("id => Array.from(document.querySelector('#workspace-select').options).some(x => x.value === id)",arg=workspace['id'])
 page.select_option('#workspace-select',workspace['id'])
 page.wait_for_selector('#chengfang-plan')
 page.locator('#chengfang-plan').select_option('smoke-plan')
 page.wait_for_selector('button[data-action="chengfang-diagnose"]')
 assert page.locator('button[data-action="chengfang-diagnose"]').is_enabled()
 assert page.locator('body').get_by_text('生成追投建议').count()==0
 assert page.locator('body').get_by_text('批准并预留').count()==0
 page.locator('button[data-action="chengfang-diagnose"]').click()
 page.wait_for_selector('[data-testid="content-decisions"]',timeout=15000)
 assert '内容决策' in page.locator('body').inner_text()
 diagnosis_export=page.locator('a[href^="/api/chengfang/diagnosis-runs/"][href$="/export"]')
 assert diagnosis_export.count()==1
 diagnosis_id=diagnosis_export.first.get_attribute('href').split('/')[4]
 frozen_text=page.locator('[data-testid="diagnosis-frozen"]').inner_text()
 # Changing live state cannot revise the saved diagnosis screen.
 assert api.put(f"/api/workspaces/{workspace['id']}/chengfang/plans/smoke-plan/materials/cf-a",data={'path':'live','labels':{**labels,'hook':'已变更'}}).ok
 changed_context={**context,'marketing_roi_target':3.5}
 assert api.put(f"/api/workspaces/{workspace['id']}/chengfang/context",data=changed_context).ok
 config['diagnosis_min_spend_yuan']=9999
 assert api.put(f"/api/workspaces/{workspace['id']}/config",data=config).ok
 page.reload(wait_until='networkidle')
 page.wait_for_selector('#chengfang-plan')
 page.locator('#chengfang-plan').select_option('smoke-plan')
 page.locator('button[data-action="view"][data-value="history"]').first.click()
 page.wait_for_selector(f'[data-action="load-chengfang-diagnosis"][data-id="{diagnosis_id}"]')
 page.locator(f'[data-action="load-chengfang-diagnosis"][data-id="{diagnosis_id}"]').click()
 page.wait_for_selector('[data-testid="diagnosis-frozen"]')
 assert page.locator('[data-testid="diagnosis-frozen"]').inner_text()==frozen_text
 assert '三秒开场' in page.locator('[data-testid="content-decisions"]').inner_text()
 export_response=api.get(diagnosis_export.first.get_attribute('href'))
 assert export_response.ok and '素材ID/标签' in export_response.text()
 api.dispose()
 assert not errors,errors
 print('UI smoke passed; browser console errors:',errors)
 (out/'browser_test.json').write_text(json.dumps({'passed':True,'console_errors':errors,'checks':['real imports and ranking','full metrics','detail view','synthetic recommendations','local approval','execution record','review','upload preview','settings','narrow viewport','chengfang frozen diagnosis and export']},ensure_ascii=False,indent=2))
 browser.close()
