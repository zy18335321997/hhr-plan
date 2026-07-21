/**
 * 明道云工作流节点批量提取 — v2（API 路径兼容版）
 *
 * 与 inject_all.js 的区别：
 *   - 不依赖 /api/worksheet/ 和 /api/process/ 路径（某些版本不存在）
 *   - 直接走 /api/workflow/flowNode/get（所有版本通用）
 *   - 使用 authorization header（md_pss_id token）
 *   - 工作表+字段名需从其他地方补充（project_context.json 或 field_map.json）
 *
 * 使用方法:
 *   1. Chrome 登录明道云，打开目标应用任意页面
 *   2. F12 → Console → 粘贴此脚本 → 回车
 *   3. 自动下载 {项目名}_nodes.json
 *
 * 前提: 需要工作流 PID 列表，可通过以下方式获取：
 *   - 在工作流列表页执行 get_pids.js 先收集 PID
 *   - 或从已有 _workflows_flat.json 读取
 */

(async function() {
  'use strict';

  const token = (document.cookie.match(/md_pss_id=([^;]+)/) || [])[1];
  if (!token) {
    console.error('未找到 md_pss_id cookie，请确认已登录明道云');
    return;
  }

  const PROJECT = new URL(location.href).hostname.replace(/\./g, '_');
  const API = location.origin + '/api/workflow/flowNode/get';
  const BATCH = 20, DELAY = 1500;

  function download(data, name) {
    const b = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = PROJECT + '_' + name;
    a.click();
  }

  // ═══════════ Phase 1: 获取 PID 列表 ═══════════
  // 从全局变量或页面数据中提取（明道云内部变量）
  console.log('[1/2] 获取工作流 PID 列表...');

  let pids = [];

  // 方法1: 从 localStorage 读（如果之前存储过）
  const stored = localStorage.getItem('_md_wf_pids');
  if (stored) {
    try { pids = JSON.parse(stored); } catch(e) {}
  }

  // 方法2: 从 URL 参数读（单条模式）
  const urlPid = new URLSearchParams(location.search).get('processId');
  if (urlPid && !pids.includes(urlPid)) {
    pids = [urlPid];
  }

  if (pids.length === 0) {
    console.warn('未找到 PID 列表。请先在 Console 执行以下命令设置 PID：');
    console.warn('  localStorage.setItem("_md_wf_pids", JSON.stringify(["pid1","pid2",...]))');
    console.warn('  或使用 URL 参数 ?processId=xxx 打开单个工作流编辑页');
    return;
  }

  console.log(`  找到 ${pids.length} 个工作流 PID`);

  // ═══════════ Phase 2: 批量提取节点 ═══════════
  console.log(`[2/2] 批量提取节点 (每批${BATCH}个, 间隔${DELAY/1000}s)...`);

  const allResults = [];
  let done = 0, failed = 0;

  async function fetchOne(pid) {
    try {
      const r = await fetch(API + '?processId=' + pid + '&count=200', {
        credentials: 'include',
        headers: {
          'authorization': 'md_pss_id ' + token,
          'x-requested-with': 'XMLHttpRequest'
        }
      });
      const d = await r.json();
      if (d.data && d.data.flowNodeMap) {
        d.data._pid = pid;
        allResults.push(d.data);
        done++;
      } else {
        failed++;
      }
    } catch(e) {
      failed++;
    }
  }

  for (let i = 0; i < pids.length; i += BATCH) {
    const batch = pids.slice(i, i + BATCH);
    await Promise.all(batch.map(fetchOne));
    console.log(`  批次 ${Math.floor(i/BATCH+1)}/${Math.ceil(pids.length/BATCH)} | OK:${done} FAIL:${failed} | ${Math.round(done/pids.length*100)}%`);

    if (i + BATCH < pids.length) {
      await new Promise(r => setTimeout(r, DELAY));
    }
  }

  console.log(`=== 完成 === OK:${done} FAIL:${failed} TOTAL:${pids.length}`);
  download(allResults, 'nodes.json');

})();
