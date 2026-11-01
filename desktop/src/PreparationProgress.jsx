import React from 'react';
import {preparationProgress} from './model.mjs';
const names={'source-check':'校验来源摘要',copy:'复制独立副本','copy-check':'校验副本摘要','source-recheck':'再次校验来源','before-commit':'准备提交新代次',completed:'新代次已提交',cancelled:'准备已记录取消'};
export default function PreparationProgress({view}){
 const value=preparationProgress(view);
 if(!value)return null;
 if(value.unavailable)return <section><h2>准备进度</h2><p>进度记录暂不可核验，已有材料保留。</p></section>;
 return <section><h2>最近保存的准备进度</h2>
  <p>{names[value.stage]} · 材料 {value.files_completed}/{value.total_files}{value.node?` · 节点 ${value.node}`:''}</p>
  {value.total_bytes>0&&<><progress value={value.bytes_processed} max={value.total_bytes}/><p>本阶段已处理 {Math.floor(value.bytes_processed/1048576)} / {Math.ceil(value.total_bytes/1048576)} MiB</p></>}
  <p>{value.request_matches?'记录对应当前操作。':'此项为先前操作记录。'}保存时间：{value.updated_at}。检查点不证明工作器仍在运行。</p>
  <p>取消会保留已有副本，可能需等待当前文件读写结束；已提交的新代次不会因迟到取消而撤销。</p>
 </section>;
}
