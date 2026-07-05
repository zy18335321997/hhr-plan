/**
 * 明道云全量数据抓取脚本 — Chrome DevTools Console 执行
 *
 * 产出 (两个文件自动下载):
 *   1. {项目名}_all_workflows.json  → 全量工作流+节点数据
 *   2. {项目名}_field_map.json       → fieldId→fieldName 全局映射表
 *
 * 使用方法:
 *   1. Chrome 登录明道云，打开目标应用
 *   2. F12 → Console → 粘贴此脚本 → 回车
 *   3. 等待两个文件自动下载完成
 *
 * 依赖: 明道云内部 API (当前页面已登录 cookie 自动携带)
 */

(async function() {
'use strict';

const APP_ID = (location.pathname.match(/\/app\/([^/]+)/) || [])[1] || '';
const PROJECT = new URL(location.href).hostname.replace(/\./g, '_');
const API = location.origin + '/api';

// ═══════════ helpers ═══════════
function post(url, body) {
  return fetch(API + url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
    credentials: 'include'
  }).then(r => r.json());
}

function get(url, params) {
  const qs = new URLSearchParams(params).toString();
  return fetch(API + url + (qs ? '?' + qs : ''), {
    credentials: 'include'
  }).then(r => r.json());
}

function download(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = PROJECT + '_' + name;
  a.click();
}

// ═══════════ Phase 1: 全量工作表 → 字段映射 ═══════════
console.log('[1/3] 获取工作表列表...');
const wsRes = await post('/worksheet/getAppWorksheetList', {appId: APP_ID});
const worksheets = wsRes.data || wsRes.worksheets || [];
console.log(`  找到 ${worksheets.length} 张工作表`);

const fieldMap = {};   // fieldId → {name, type, sheetName}
const sheetNames = {}; // sheetId → sheetName

for (let i = 0; i < worksheets.length; i++) {
  const ws = worksheets[i];
  const wsId = ws.worksheetId || ws.id || '';
  const wsName = ws.workSheetName || ws.name || wsId;
  sheetNames[wsId] = wsName;

  if (wsId) {
    try {
      const struct = await post('/worksheet/getWorksheetStructure', {
        appId: APP_ID,
        worksheetId: wsId
      });
      const controls = struct.data?.controls || struct.controls || [];
      for (const c of controls) {
        fieldMap[c.controlId || c.id || ''] = {
          name: c.controlName || c.name || '',
          type: c.type || 0,
          sheet: wsName
        };
      }
      if ((i + 1) % 10 === 0) console.log(`  ${i + 1}/${worksheets.length} 工作表...`);
    } catch(e) {
      // 跳过提取失败的工作表
    }
  }
}

const fieldCount = Object.keys(fieldMap).length;
console.log(`  字段映射: ${fieldCount} 个字段`);
download('field_map.json', {fieldMap, sheetNames, total: fieldCount});

// ═══════════ Phase 2: 全量工作流 → 节点数据 ═══════════
console.log('[2/3] 获取工作流列表...');
const wfRes = await post('/process/getProcessList', {
  appId: APP_ID,
  pageIndex: 1,
  pageSize: 1000
});
const wfList = wfRes.data?.list || wfRes.data || wfRes.list || [];
console.log(`  找到 ${wfList.length} 个工作流`);

const allWf = [];
for (let i = 0; i < wfList.length; i++) {
  const wf = wfList[i];
  const pid = wf.processId || wf.id || '';
  if (!pid) continue;

  try {
    // 获取完整节点链
    const detail = await post('/flowNode/get', {
      processId: pid,
      instanceId: ''
    });
    const nodes = detail.data?.flowNodes || detail.flowNodes || [];

    // 为每个节点补全 fieldName
    for (const node of nodes) {
      if (node.fields && Array.isArray(node.fields)) {
        for (const f of node.fields) {
          const fid = f.fieldId || f.controlId || '';
          if (fid && (!f.fieldName || f.fieldName === null)) {
            const fm = fieldMap[fid];
            if (fm) {
              f.fieldName = fm.name;
              f.fieldTypeName = fm.type;
            }
          }
        }
      }

      // 补全 conditionValues 的字段名
      if (node.operateCondition && Array.isArray(node.operateCondition)) {
        for (const group of node.operateCondition) {
          if (!Array.isArray(group)) continue;
          for (const cond of group) {
            if (cond.conditionValues && Array.isArray(cond.conditionValues)) {
              for (const cv of cond.conditionValues) {
                const cid = cv.controlId || '';
                if (cid && cv.controlName === '') {
                  const fm = fieldMap[cid];
                  if (fm) cv.controlName = fm.name;
                }
              }
            }
          }
        }
      }

      // 审批人字段补全
      if (node.accounts && Array.isArray(node.accounts)) {
        for (const a of node.accounts) {
          if (a.entityId && !a.entityName) {
            const fm = fieldMap[a.entityId];
            if (fm) a.entityName = fm.name;
          }
        }
      }
    }

    allWf.push({
      processId: pid,
      name: wf.name || wf.processName || '',
      triggerName: wf.triggerName || '',
      triggerType: wf.triggerType || 0,
      triggerId: wf.triggerId || '',
      worksheetName: wf.worksheetName || sheetNames[wf.worksheetId] || '',
      nodeCount: nodes.length,
      isEnabled: wf.isEnabled,
      nodes: nodes
    });

    if ((i + 1) % 20 === 0) console.log(`  ${i + 1}/${wfList.length} 工作流...`);
  } catch(e) {
    // 跳过提取失败的工作流
  }
}

console.log(`  提取完成: ${allWf.length} 个工作流`);
download('all_workflows.json', {workflows: allWf, total: allWf.length});

console.log('[3/3] ✓ 完成! 两个文件正在下载...');
console.log(`  工作表: ${worksheets.length}, 字段映射: ${fieldCount}, 工作流: ${allWf.length}`);

})();
