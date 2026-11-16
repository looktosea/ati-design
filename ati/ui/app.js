'use strict';
const $ = id => document.getElementById(id);
const titles = {candidates:['尾盘候选','把注意力，留给值得研究的信号。'],review:['信号复盘','记录每次判断，也看见后续表现。'],quality:['数据健康','可信的研究，从完整的数据开始。'],guide:['使用指南','从一条信号开始，建立研究习惯。']};
const factorNames = {I01:'行业相对强度',I02:'趋势结构',I03:'回调恢复',I04:'区间突破',I06:'价格与均价关系',I07:'日内价格位置',M06:'涨跌停密度',S01:'板块相对强度',S02:'板块上涨宽度',S05:'板块强度持续性',R01:'价格过热'};
const labels = {VALID:'发布时有效',NO_CANDIDATE:'无候选',BLOCKED:'数据阻断',PENDING:'等待评价',EVALUATED:'已评价',DATA_UNRESOLVED:'终点数据缺失',ENTRY_UNCERTAIN:'参考价不确定',RANK_LIMIT:'未进入前列',REQUIRED_FACTOR_INVALID:'必要因子缺失或历史不足',ST_EXCLUDED:'ST 证券已排除',ST_STATUS_UNKNOWN:'ST 状态未确认',NO_MARKET_SNAPSHOT:'尚未采集市场行情',NON_TRADING_DAY_OR_CALENDAR_MISSING:'非交易日或交易日历缺失',SNAPSHOT_SOURCE_NOT_VALID:'行情来源状态未通过',L1_HISTORY_OR_ELIGIBILITY_INSUFFICIENT:'历史数据或筛选条件不足',STALE_QUOTE_SNAPSHOT:'最新行情已过期',NO_QUOTE_SNAPSHOT:'尚无行情快照',DAILY_HISTORY_EMPTY:'尚无历史日线',DAILY_HISTORY_COVERAGE_LOW:'日线覆盖不足',UNIVERSE_SNAPSHOT_MISMATCH:'行情证券与股票池不匹配',DUPLICATE_FACTOR_KEYS:'因子业务键重复',INVALID_QUOTE_TIMESTAMP:'行情时间格式异常',PRICE_EXTENDED:'价格偏离均线较大',NEED_60_DAYS_AND_ATR14:'需要至少 60 日历史和 ATR',NEED_HISTORY_AND_ATR14:'历史与波动率数据不足',SECTOR_MEMBERSHIP_REQUIRED:'缺少板块成员',INDUSTRY_RETURN_INSUFFICIENT:'行业对照数据不足',SECTOR_HISTORY_REQUIRED:'缺少板块历史',LIMIT_STATISTICS_REQUIRED:'缺少涨跌停统计'};
const text = value => labels[value] || value || '—';
const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const numeric = value => typeof value === 'number' && Number.isFinite(value);
const pct = value => numeric(value) ? `${value>0?'+':''}${(value*100).toFixed(2)}%` : '—';
const number = value => numeric(value) ? value.toFixed(2) : '—';
const time = value => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)) : '—';
const metric = (label,value,hint,small=false) => `<article class="metric"><div class="label">${esc(label)}</div><div class="value ${small?'text':''}">${esc(value)}</div><div class="hint">${esc(hint)}</div></article>`;
const empty = (title,description) => `<div class="empty"><b>${esc(title)}</b>${esc(description)}</div>`;
let data = null, selected = null, horizon = 3, rejectionLimit = 30, requestSequence = 0;
function setView(view) {
  if (!titles[view]) view='candidates';
  document.querySelectorAll('.view').forEach(el=>el.hidden=el.id!==view);
  document.querySelectorAll('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===view); if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('breadcrumb').textContent=titles[view][0]; $('page-title').textContent=titles[view][1];
}
function render() {
  const report=data.report, signal=report?.signal, candidates=report?.candidates||[];
  $('mode').textContent=data.mode==='demo'?'合成数据 · 演示模式':'本地记录 · 只读';
  const demo=data.mode==='demo', quality=data.quality;
  $('notice').className='notice'+(demo||quality?.status==='BLOCKED'||signal?.data_status==='BLOCKED'?' warn':'');
  $('notice').textContent=demo?'演示模式：候选与后续表现均来自合成数据，仅用于体验产品流程。':data.message||(!signal?'尚无信号记录。完成数据采集和信号计算后，刷新即可查看。':quality?.status==='BLOCKED'?'当前数据检查未通过，请到「数据健康」查看原因。下方保留历史信号，不能视为实时结果。':'正在查看已保存的历史研究记录。刷新仅重新读取本地数据库；信号不代表当前可交易。');
  $('signal-select').innerHTML=(data.signals||[]).length?data.signals.map(s=>`<option value="${esc(s.signal_id)}">${esc(time(s.decision_cutoff))} · ${esc(text(s.data_status))}</option>`).join(''):'<option value="">暂无信号</option>';
  $('signal-select').disabled=!(data.signals||[]).length;
  if(signal)$('signal-select').value=signal.signal_id;
  $('export').disabled=!report;
  const ev=report?.evaluations||[];
  $('metrics').innerHTML=metric('候选数量',signal?String(candidates.length).padStart(2,'0'):'—','当前信号的已保存候选')+metric('信号状态',text(signal?.data_status),'仅代表发布时状态',true)+metric('行情截至',signal?time(signal.market_asof).split(' ')[1]||'—':'—',signal?time(signal.market_asof).split(' ')[0]:'暂无行情',true)+metric('3 日评价',`${ev.filter(e=>e.horizon_days===3&&e.status==='EVALUATED').length} / ${candidates.length}`,'已评价 / 候选数');
  $('candidate-count').textContent=candidates.length;
  if(!candidates.some(c=>c.security_id===selected))selected=candidates[0]?.security_id||null;
  $('candidate-list').innerHTML=candidates.length?candidates.map(c=>`<button class="candidate ${selected===c.security_id?'selected':''}" data-security="${esc(c.security_id)}" aria-pressed="${selected===c.security_id}"><span class="rank">${String(c.rank).padStart(2,'0')}</span><span><strong>${esc(c.security_id)}</strong><small>${demo?'合成演示证券':'研究候选'} · ${(c.factor_refs||[]).length} 项因子引用</small></span><span class="score">${number(c.score)}<small>排序分数</small></span></button>`).join(''):empty(signal?.data_status==='BLOCKED'?'本次信号已阻断':'暂无可展示候选',text(signal?.data_status_reason)||'完成采集后刷新记录');
  renderDetail();renderRejections();renderReview();renderQuality();
  $('loaded-at').textContent=`读取时间 ${time(data.loaded_at)} · Asia/Shanghai`;
}
function renderDetail() {
  const c=data?.report?.candidates.find(c=>c.security_id===selected);
  if(!c){$('detail').innerHTML=empty('依据会在这里呈现','有候选时，选择一项查看已有证据与风险。');return;}
  document.querySelectorAll('[data-security]').forEach(el=>{el.classList.toggle('selected',el.dataset.security===selected);el.setAttribute('aria-pressed',el.dataset.security===selected);});
  const refs=c.factor_refs||[];
  const evidence=(c.evidence||[]).map(e=>{const match=/^([A-Z]\d{2}) valid$/.exec(e);return match?`${factorNames[match[1]]||match[1]}：计算有效`:e;});
  $('detail').innerHTML=`<div class="detail-head"><span class="eyebrow">SIGNAL INSIGHT / 信号详情</span><span class="badge">排名 ${esc(c.rank)}</span></div><h3>${esc(c.security_id)}</h3><div class="code">${data.mode==='demo'?'合成演示样本':'证券名称未随报告保存'} · ${esc((c.strategy_ids||[]).join(' / '))}</div><div class="detail-section"><b>入选依据</b>${refs.map(ref=>{const id=ref.split(':')[0];return `<div class="evidence"><span class="icon">✓</span><div>${esc(factorNames[id]||id)}<small>${esc(ref)}</small></div><span class="pill">已有引用</span></div>`;}).join('')||'<p>暂无因子引用</p>'}</div><div class="detail-section"><b>已保存的解释</b><p class="caption">${evidence.map(esc).join('；')||'暂无解释记录'}。因子有效只代表可计算，并不自动代表趋势向好。</p></div><div class="detail-section"><b>需要留意</b><div class="risk">${(c.risks||[]).length?c.risks.map(r=>esc(text(r))).join('<br>'):'当前记录未列出风险标签；不代表没有风险。'}</div></div><div class="meta">信号版本 ${esc(data.report.signal.strategy_version)}<br>注册表 ${esc(data.report.signal.factor_registry_version)}</div>`;
}
function renderRejections() {
  const rows=data?.report?.rejections||[], query=$('search').value.trim().toLowerCase();
  const filtered=rows.filter(r=>`${r.security_id} ${text(r.reason_code)} ${JSON.stringify(r.details||{})}`.toLowerCase().includes(query));
  $('rejection-count').textContent=rows.length;
  $('rejection-list').innerHTML=filtered.slice(0,rejectionLimit).map(r=>`<div class="rejection-row"><span>${esc(r.security_id)}</span><span>${esc(text(r.reason_code))}<small>${(r.details?.missing||[]).map(m=>`${esc(factorNames[m.factor_id]||m.factor_id)}：${esc(text(m.reason))}`).join(' / ')}</small></span></div>`).join('')||'<p class="caption">没有匹配的排除记录。</p>';
  $('more').hidden=filtered.length<=rejectionLimit;
  $('more').textContent=`显示更多（已显示 ${Math.min(rejectionLimit,filtered.length)} / ${filtered.length}）`;
}
function renderReview() {
  const report=data?.report;
  const rows=(report?.candidates||[]).map(c=>{const records=(report.evaluations||[]).filter(e=>e.security_id===c.security_id&&e.horizon_days===horizon).sort((a,b)=>(b.evaluated_at||'').localeCompare(a.evaluated_at||''));return records[0]||{security_id:c.security_id,status:'PENDING'};});
  const evaluated=rows.filter(e=>e.status==='EVALUATED'), returns=evaluated.map(e=>e.net_reference_return).filter(numeric);
  $('review-metrics').innerHTML=metric('观察窗口',`${horizon} 个交易日`,'以交易日历计算',true)+metric('已评价',`${evaluated.length} / ${rows.length}`,'保留未完成的样本')+metric('平均参考净收益',returns.length?pct(returns.reduce((a,b)=>a+b,0)/returns.length):'—',`有效收益记录 ${returns.length} 条`)+metric('待完成',String(rows.length-evaluated.length),'等待终点 / 补齐数据');
  $('evaluation-list').innerHTML=rows.map(e=>`<tr><td>${esc(e.security_id)}</td><td>${esc(text(e.status))}</td><td>${number(e.reference_price)}</td><td class="${numeric(e.net_reference_return)?e.net_reference_return>=0?'positive':'negative':''}">${pct(e.net_reference_return)}</td><td>${pct(e.max_adverse_move)}</td><td>${esc(e.endpoint_trade_date)}</td></tr>`).join('')||'<tr><td colspan="6">暂无候选评价。请先选择有候选的信号。</td></tr>';
}
function renderQuality() {
  const q=data?.quality, signal=data?.report?.signal;
  if(data?.mode==='demo'){$('quality-content').innerHTML=empty('演示数据，与本地数据隔离','此模式不会读取生产库，也不会调用行情服务。请用不带 --demo 的命令查看本地数据状态。');return;}
  if(!q){$('quality-content').innerHTML=empty('尚无数据健康报告',data?.message||'先初始化本地数据库。');return;}
  const fraction=v=>numeric(v)?`${(v*100).toFixed(1)}%`:'—';
  const age=numeric(q.latest_quote_age_seconds)?(q.latest_quote_age_seconds<0?'时间异常':`${Math.floor(q.latest_quote_age_seconds/60)} 分钟`):'—';
  $('quality-content').innerHTML=`<div class="metrics">${metric('当前数据检查',q.status==='VALID'?'检查通过':'检查未通过','检查范围见下方',true)}${metric('股票池报价覆盖',fraction(q.quote_universe_coverage),'有报价的股票池成员 / 股票池')}${metric('最新行情距今',age,'当前时间与行情时间的差值',true)}${metric('历史失败 / 阻断任务',String(q.failed_or_blocked_jobs),'累计记录，非当前故障数')}</div><div class="panel"><div class="quality-row"><div><b>当前检查原因</b><p>${(q.reasons||[]).map(r=>esc(text(r))).join('；')||'现有检查未发现问题。'}</p></div><span class="badge">${time(q.checked_at)}</span></div><div class="quality-row"><div><b>所选历史信号</b><p>${esc(text(signal?.data_status_reason))}</p></div><span>${esc(text(signal?.data_status))}</span></div>${Object.entries(q.counts||{}).map(([key,value])=>`<div class="quality-row"><span>${esc(({source_batch:'数据批次',security_master_snapshot:'股票名录记录',trading_calendar:'交易日历记录',daily_bar:'个股日线记录',quote_snapshot:'行情记录',index_master:'板块目录',index_membership_snapshot:'板块成员记录',factor_value:'因子记录',signal_snapshot:'信号记录',signal_candidate:'候选记录',signal_candidate_evaluation:'候选评价',job_run:'任务记录',shadow_observation:'影子源观察'})[key]||key)}</span><b>${esc(value)}</b></div>`).join('')}</div><article class="panel quality-note"><h2>如何理解这些检查</h2><p>当前门控存在审核报告列出的时点与覆盖缺口。「检查通过」不等同于数据或策略已完成全部验证。</p><p>这里的报价覆盖按股票池重新计算；历史信号的发布状态保留原始记录。</p></article>`;
}
async function load(signalId) {
  const seq=++requestSequence;$('refresh').disabled=true;$('export').disabled=true;$('notice').textContent='正在读取本地记录…';
  try {
    const response=await fetch('/api/dashboard'+(signalId?'?signal_id='+encodeURIComponent(signalId):''),{cache:'no-store'});
    const payload=await response.json();if(!response.ok)throw new Error(payload.message||'读取失败');
    if(seq!==requestSequence)return;
    data=payload;rejectionLimit=30;render();
  } catch(error) {
    if(seq!==requestSequence)return;
    // Clear stale results: a failed refresh must not leave a usable-looking report.
    data={mode:data?.mode||'local',report:null,signals:[]};render();
    $('notice').className='notice error';$('notice').textContent=`读取失败：${error.message} 请点击「刷新记录」重试。`;
  } finally {if(seq===requestSequence)$('refresh').disabled=false;}
}
document.querySelectorAll('[data-view]').forEach(el=>el.addEventListener('click',()=>{location.hash=el.dataset.view;setView(el.dataset.view);}));
window.addEventListener('hashchange',()=>setView(location.hash.slice(1)));
$('candidate-list').addEventListener('click',event=>{const button=event.target.closest('[data-security]');if(button){selected=button.dataset.security;renderDetail();}});
document.querySelectorAll('[data-horizon]').forEach(el=>el.addEventListener('click',()=>{horizon=Number(el.dataset.horizon);document.querySelectorAll('[data-horizon]').forEach(b=>{b.classList.toggle('active',b===el);b.setAttribute('aria-pressed',b===el);});renderReview();}));
$('search').addEventListener('input',()=>{rejectionLimit=30;renderRejections();});
$('more').addEventListener('click',()=>{rejectionLimit+=30;renderRejections();});
$('signal-select').addEventListener('change',()=>load($('signal-select').value));
$('refresh').addEventListener('click',()=>load($('signal-select').value||undefined));
$('export').addEventListener('click',()=>{if(!data?.report)return;const blob=new Blob([JSON.stringify({mode:data.mode,exported_at:new Date().toISOString(),report:data.report},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`ati-${data.mode}-${data.report.signal.trade_date}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
setView(location.hash.slice(1));
if(window.ATI_PREVIEW){data=window.ATI_PREVIEW;render();$('refresh').disabled=true;$('refresh').title='离线界面预览';$('signal-select').disabled=true;}else load();
