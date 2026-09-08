# 进度变更日志（倒序）

## 2026-09-07 — PLAT-RUN-BRANCHES done（run 并列分支）

- **缺口**：`dim_clip.active_run_id` 把总览/检索/Dataset/校核收成每 clip 一行，后跑的 NVH 会藏起舱内分支
- **实现**：列表粒度 `(clip_id, run_id)`；OMS 枚举所有合格 pipeline_run；检索/Dataset/校核认全部打标分支；失败 run 不限 active 可重试；总览 `rowKey` + `?run_id=`；去掉「当前生效」
- **验收**：`acceptance/PLAT-RUN-BRANCHES.md`；A run_branches **6/6**、audio_nvh_view **5/5**、dataset m42 OK；A-E2E overview-run-branches **1/1 (10.9s)**
- **未做**：云端 MC 单指针；DataWorks；publish `audio_nvh-v2`；H-2
- **未 git commit**；推荐下一工单可选 M7.5-E2E

## 2026-09-07 — PLAT-DAG-IO-CONTRACT done（DAG I/O 契约）

- **缺口**：编排连线/期望产出与 kernel 实际消费不一致；磁盘碰巧有 wav 也会喂 Omni
- **实现**：`io_contract.py` 诊断最小输入与封闭绑定；全量只吃绑定；缺期望产物在生产者失败；检查器期望输出 + `until_key` 试跑；画板黄叹号
- **验收**：`acceptance/PLAT-DAG-IO-CONTRACT.md`；A io_contract **14/14**、kernel **10/10**、graph_runtime **9/9**、catalog **9/9**、recipe_graph **33/33**；A-E2E editor **14/14 (50.5s)**
- **未做**：DataWorks；publish `audio_nvh-v2`；H-2；IVI 业务打标
- **未 git commit**；推荐下一工单可选 M7.5-E2E

## 2026-09-07 — PLAT-CAPABILITY-KERNEL done（`text_to_json`）

- **缺口**：kernel 本地 catalog 只缺 `text_to_json`，未实现时报 `capability 未实现`
- **实现**：`graph_runtime._adapt_text_to_json` 读 manifest 文本；`generic_json` / `generic_text`；写 `ctx.structured_json` + `structured.json`；下游 `json_extract` 可接
- **验收**：`acceptance/PLAT-CAPABILITY-KERNEL.md`；A kernel **10/10**、graph_runtime **9/9**、progress_steps **9/9**、catalog_ops **9/9**
- **未做**：DataWorks；publish `audio_nvh-v2`；H-2；IVI 业务打标
- **未 git commit**；推荐下一工单可选 M7.5-E2E

## 2026-09-04 — UI-NVH-REVIEW-SAVE done（语义 L6 人工写回）

- **缺口**：Explorer 标签树只读；`clip_label_review` 不写 `fact_clip_label` / `nvh_labels.json`；rollup/队列把全部客观 NVH 叶子算进去
- **实现**：`review/nvh_writeback.py` 只 merge `nvh.sem.*`；校核保存与 field review 挂钩；队列/rollup 仅 L6；Explorer 仅 L6 快速校核
- **验收**：`acceptance/UI-NVH-REVIEW-SAVE.md`；A `test_nvh_review_save` 3/3、`test_review_m61` ok；A-E2E `nvh-label-tree.spec.ts` **2/2 (9.3s)**
- **未做**：publish `audio_nvh-v2`；H-2；DataWorks
- **未 git commit**；推荐下一工单 PLAT-CAPABILITY-KERNEL（`text_to_json`）

## 2026-09-04 — FIX-ENCODE-FFMPEG（视频编码器找不到 ffmpeg）

- **现象**：oms_cabin DAG 视频编码器失败，`No ffmpeg exe could be found ... IMAGEIO_FFMPEG_EXE`
- **根因**：本机 PATH 无 `ffmpeg`；`imageio_ffmpeg.get_ffmpeg_exe()` 的 `_is_valid_exe` 失败时抛 RuntimeError；`clip_video._resolve_ffmpeg` 只 catch `ImportError`
- **修复**：`resolve_ffmpeg()` 直接用 `imageio_ffmpeg/binaries/ffmpeg*`；worker 开跑前钉 `IMAGEIO_FFMPEG_EXE`；HMI `preview_mp4` 走同一解析
- **验收 A**：`test_clip_video_ffmpeg` 3/3；bbox 15/15；本机 encode smoke 写出 MP4
- **未 git commit**；推荐下一工单仍是 UI-NVH-REVIEW-SAVE

## 2026-09-04 — PLAT-CAPABILITY-KERNEL slice-2

- **方向**：`audio_array_spec` 有 graph 时与舱内一样走 capability kernel；本地 NVH 插件接现有 `analyze_pcm_pa` / deriver
- **实现**：`capability_nvh.py`；worker 去掉「有图仍专用路径」；无 graph 阵列仍 `_run_audio_array_spec`
- **验收 A**：`test_capability_kernel.py` 5/5；`test_platform_graph_runtime.py` 9/9；`test_platform_progress_steps.py` 9/9
- **未做**：`text_to_json`；DataWorks；publish `audio_nvh-v2`
- **未 git commit**；推荐下一工单仍是 UI-NVH-REVIEW-SAVE

## 2026-09-04 — PLAT-CAPABILITY-KERNEL slice-1

- **方向**：一个 runtime kernel + 可插拔 capability，不拆成一组件一 SDK 包
- **规格**：`docs/superpowers/specs/2026-09-04-capability-runtime-kernel-design.md`
- **实现**：`capability_kernel.py` 注册表；`capability_sdk.py` 单步 `run_plan`；有 graph 的舱内 run 走 `execute_recipe_graph`；ASR/打标后 if 已放开；进度优先 `dag:{node_key}`
- **验收 A**：`test_capability_kernel.py` 4/4；`test_platform_graph_runtime.py` 9/9；`test_platform_progress_steps.py` 9/9
- **未做**：Mel/STFT 等本地音频插件；DataWorks；阵列类型仍专用路径；无 graph 仍 `plan_and_run`
- **未 git commit**；推荐下一工单仍是 UI-NVH-REVIEW-SAVE

## 2026-09-03 — UI-DTYPE-DAG-CANVAS done（Playwright 收口）

- **工单**：编辑器 DAG 画板 + 本地按图执行 + 橱窗锁 `labels_tree`；Task 12 A-E2E 收工
- **验收**：`acceptance/UI-DTYPE-DAG-CANVAS.md`；recipe_graph **24/24**；graph_runtime **8/8**；editor **26/26**；kernel **19/19**；`tsc -b` ok；Playwright editor **3/3 (13.3s)**
- **护栏**：ASR/标签 if 本地仍 RuntimeError「本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支」，符合计划 Task 11
- **未改**：DataWorks；勿 publish audio_nvh-v2；无 git commit
- **下一**：UI-NVH-REVIEW-SAVE

## 2026-09-03 — UI-DTYPE-DAG-CANVAS 实现计划

- **计划**：`docs/superpowers/plans/2026-09-03-dtype-dag-canvas.md`（Task 1–12；A 图校验/投影 → B 画板 → C 锁树 → D runtime 护栏 → E 黄警告）
- **缺口（写进计划）：** 本地尚未拆 `plan_and_run`；ASR/标签 if 保存允许、开跑会 RuntimeError
- **未写**：业务代码；未 git commit

## 2026-09-03 — UI-DTYPE-DAG-CANVAS spec 拍板落盘

- **诉求**：编辑器做成 Coze/LangGraph/Airflow 式 DAG；逻辑 if/else；`/w/:id` 橱窗必展示标签树
- **文档**：`docs/superpowers/specs/2026-09-03-dtype-dag-canvas-design.md`（D1–D12）；源节点 spec S8 改为被本文件取代
- **范围**：本地按图执行；DataWorks 只跑公共前缀；不 publish audio_nvh-v2
- **未写**：业务代码；未 git commit spec
- **下一**：审 spec → 实现计划；UI-NVH-REVIEW-SAVE 排后

## 2026-09-03 — UI-DTYPE-SOURCE-NODES 编辑器 polish（打标器固定最后）

- **诉求**：评审偏差 1–5 + 打标器永远是最后一个节点（管线输出标签树）
- **实现**：首页去掉「源槽位」文案；「允许后缀」；种子 `title`（舱内 bag 等）；保存前中文重名校验；`pinLabelLast`；新算子插到打标器前；打标器不可拖/删
- **验收**：editor **26/26**；kernel **19/19**；`tsc -b` ok；Playwright editor **3/3**
- **未改**：DataWorks；勿 publish audio_nvh-v2
- **下一**：UI-NVH-REVIEW-SAVE

## 2026-09-02 — UI-DTYPE-SOURCE-NODES Task 8（切片 B Playwright 收工）

- **命令**：`cd hmi/frontend && cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts e2e/platform-lake.spec.ts"`
- **结果**：**7 passed (48.2s)** = editor **3/3** + lake **4/4**
- **覆盖**：wav 入湖 → `/pipeline?tab=run` → `audio_array_spec` → `lake-run-slot-audio_primary` 勾选预检通过；`ivi_ui_stub` 下 `.txt` 不进 `lake-run-slot-ui_media`
- **文档**：`acceptance/UI-DTYPE-SOURCE-NODES.md` 刷新执行记录；推荐下一仍 **UI-NVH-REVIEW-SAVE**
- **未改**：DataWorks；勿 publish audio_nvh-v2；无 git commit

## 2026-09-02 — UI-DTYPE-SOURCE-NODES（数据源节点 + 开跑分源）

- **问卷**：S1 删独立源槽位表；S2 源节点（一源多文件）；S3 开跑 `manual_map` 分块勾选；S4 产物名 `label_only`
- **实现**：`validate_source_assignments`；`POST /runs` 收 `assignments`；多 slot 禁止裸 `source_ids`；`LakeRunBindPanel` 每 slot 一块 `lake-run-slot-{id}`
- **验收**：bind **9/9**；kernel **19/19**；editor **23/23**；`tsc -b` ok；e2e editor **3/3** + lake **4/4**（Task 8 复验 7/7 · 48.2s）
- **未改**：DataWorks；worker 阶段顺序；勿 publish audio_nvh-v2
- **下一**：UI-NVH-REVIEW-SAVE

## 2026-09-02 — 数据源卡内追加输入行

- **诉求**：点「添加数据源」不要再长出一张卡，只在数据源卡里新增一路输入
- **实现**：编排顶部固定一张数据源卡；多路源是卡内行（仍编译为各自 slot）；oms_cabin 为 1 卡 4 行
- **验收**：editor e2e **3/3**

## 2026-09-02 — UI-DTYPE-OVERVIEW-COMPOSE（总览组件拼版）

- **诉求**：总览不要只选整页模板；列表和 Clip 详情要像管线那样叠组件卡
- **实现**：`recipe.overview.list/detail`；`overview_view` 为预设一键填入；编辑器两套拼版；Overview / Explorer / 校核按卡渲染（空 detail 仍 bootstrap 兜底）
- **验收**：kernel **19/19**；editor **23/23**；`tsc -b` ok；e2e editor **3/3**
- **未改**：DataWorks；worker；勿 publish audio_nvh-v2

## 2026-09-02 — UI-DTYPE-PIPELINE-ORCH（parse_bag 产出连续帧）

- **诉求**：ROSBAG 解析器解析的是连续帧，不是成片视频
- **实现**：`PARSE_BAG_MODALITIES = frames / .wav / .json`；旧 `video|.mp4` hydrate 成 `frames`；编码器可绑「ROSBAG 解析器 · 连续帧」
- **验收**：editor **12/12**；kernel **15/15**；e2e editor **3/3**；`tsc -b` ok

## 2026-09-02 — UI-DTYPE-PIPELINE-ORCH（kind = 入湖文件后缀）

- **诉求**：不要用泛型「视频/音频」当 kind；kind 以上传到湖里的文件后缀为准
- **实现**：`file_kinds.py` / `fileKinds.ts`；入库优先文件名后缀；旧 `video|audio|image|text|rosbag` 读时归一；解析产出 `.mp4` `.wav` `.json`
- **验收**：editor **12/12**；kernel **15/15**；lake **6/6**；e2e editor **3/3** + lake **4/4**；`tsc -b` ok
- **未改**：SDK ingest 内部仍用 video.mp4 等文件名；DataWorks；勿 publish audio_nvh-v2

## 2026-09-02 — UI-DTYPE-PIPELINE-ORCH（视频编码器不再吃视频）

- **诉求**：`encode_preview` 输入不要「视频」chip，也不要绑解析器视频产物
- **实现**：输入端口仅 `frames`/`image`；`TYPE_PROVIDES.video` 不再等价于帧/图（视频走抽帧）
- **验收**：editor **12/12**；e2e **3/3**（编码器无视频 chip；绑定可见「视频抽帧 · 连续帧」）

## 2026-09-02 — UI-DTYPE-PIPELINE-ORCH（parse_bag 产出视频/音频/文本）

- **诉求**：解析器产出不要「多模数据」一种 kind；参数里勾选视频/音频/文本，作为产物接到后续节点
- **实现**：`emit_modalities`；卡上「解析产出」多选；下游绑定 `ROSBAG 解析器 · 音频` 等；旧 `frames_audio_topics` hydrate 成三项
- **验收**：editor **11/11**；kernel **15/15**；e2e **3/3**；`tsc -b` ok
- **未改**：worker / DataWorks 仍不按 `emit_modalities` 裁剪解析

## 2026-09-02 — UI-DTYPE-PIPELINE-ORCH（DataType 管线编排组件卡）

- **UI**：`DataTypeEditorPage` 拆掉「预处理列表 + 管线能力开关」，改为左侧 SDK 目录 + 有序组件卡（输入/产出/参数）
- **目录**：`operators.py` 补端口、分组、`label`/`embed`（`role=stage`）；`GET /operators` 带 `type_provides`
- **编译**：卡 → 现有 `preprocess` / `stages` / `bbox`；worker / DataWorks 不改
- **验收**：`acceptance/UI-DTYPE-PIPELINE-ORCH.md`；editor 单测 **9/9**；e2e **3/3**
- **未改**：执行路径；勿 publish audio_nvh-v2

## 2026-08-28 — FIX-SPA-PREFIX（直连 :8012 子路径空白页）

- **原因**：生产前端 `VITE_BASE=/tools/rosbag-labels/`，直连 8012 时 JS/CSS 打到该前缀，SPA fallback 把脚本当成 HTML
- **修复**：`hmi/public_prefix.py` + `strip_public_ui_prefix` 中间件；nginx 已剥前缀时 no-op
- **验收**：`py -3 hmi/backend/scripts/test_public_ui_prefix.py` 通过
- **发布**：须重新 `save-image.ps1` 再 load 到 POC

## 2026-08-27 — DOC-INTRANET-CICD（域内部署交接）

- **文档**：`docs/deploy-intranet-cicd.md`（堡垒机登录、Dockerfile、仓库根 save、SFTP、POC load/run 参数）
- **脚本**：`hmi/deploy/save-image.ps1`
- **约束**：Word 指南中的堡垒机口令不入库；账号交接后向 CI 改绑
- **验收**：`acceptance/DOC-INTRANET-CICD.md`

## 2026-08-25 — DOC-HANDOVER（项目交接文档 + Agent 技能包）

- **文档**：`docs/HANDOVER.md`、`docs/architecture.md`、`docs/CODE_MAP.md`；刷新 `docs/WIKI.md`
- **技能**：`.cursor/skills/rosbag-onboarding|platform-kernel|hmi-dev|sdk-pipeline`；打包说明 `handover/`
- **代码**：关键入口模块级中文注释（main/platform/data_source/SDK driver/App.tsx 等）
- **压缩包**：`py -3 handover/pack_handover.py` → `handover-output/`
- **验收**：`acceptance/DOC-HANDOVER.md`
- **未改**：DataWorks 业务节点逻辑；未 publish audio_nvh-v2

## 2026-08-21 — PLAT-AUDIO-AST-LABEL（麦克风阵列 L6 用 AST AudioSet）

- **模型**：YuanGongND AST 架构 + 本地 HF `pytorch_model.bin`（527 类）；q/k/v remap 成 fused qkv
- **写入**：只覆盖 `nvh.sem.noise_category` / `noise_sources`；`quality_grade` 等仍 heuristic；hypothesis 含 top-k 分数
- **预处理**：16 kHz Kaldi 128-mel、AudioSet mean/std；四通道 RMS 混单声道
- **回退**：缺 torchaudio / 权重 → `heuristic_fallback`
- **验收**：`acceptance/PLAT-AUDIO-AST-LABEL.md`；`test_nvh_ast_label.py` **7/7**；权重 `strict_load OK`
- **约束**：勿 publish `audio_nvh-v2`；勿 DataWorks；勿提交 330MB 权重

## 2026-08-20 — UI-DTYPE-EDITOR（新建/编辑数据类型配方）

- **入口**：数据类型首页「新建数据类型」/ 卡片「编辑」（admin）
- **表单**：元信息 · 源槽位 kinds · 预处理算子→中间产物 · label/embed/bbox 开关；可从已有类型复制
- **API**：`GET /platform/operators` + `PUT /platform/data-types/{id}`（既有校验）
- **验收**：`acceptance/UI-DTYPE-EDITOR.md`；upsert **2/2**；e2e **2/2**；`tsc -b` ok
- **约束**：勿 publish `audio_nvh-v2`；新算子仍须发版注册

## 2026-08-20 — UI 信息架构：源湖只入库+OSS；开跑进管线管理

- **诉求**：源湖不要筛源/开跑；执行全在管线管理；OSS 并入源湖
- **改动**：`LakeManagePage` = 源文件入库 + OSS 浏览 Tab；`PipelineManagePage` 增「源湖开跑」Tab（`LakeRunBindPanel`）；侧栏去掉独立 OSS；`/oss` → `/lake?tab=oss`
- **验收**：`platform-lake.spec.ts` + `pipeline-datatype-run` **5/5**；`tsc -b` ok
- **未改**：DataWorks / publish audio_nvh-v2

## 2026-08-20 — DOC-DTYPE-SLOTS + PLAT-LAKE-RUN-BIND + PLAT-PRODUCT-LINEAGE

- **产品拍板**：展示按采集批；绑定按开跑多选；Sample 内部化；DataType 配方 slots；产物血缘可查
- **规格**：内核 design D9–D11；种子配方写死 slots（`audio_array_spec` / `oms_cabin` / `ivi_ui_stub`）
- **开跑**：`eligible_for` 筛源；`POST /runs` + `source_ids` → `create_sample`+`create_run`；湖页去掉主路径「组 Sample」
- **血缘**：`GET /api/platform/lineage`；`platform_product.artifact_path/run_id`；worker `audio_array_spec` 写 product 行
- **验收**：`DOC-DTYPE-SLOTS` / `PLAT-LAKE-RUN-BIND` / `PLAT-PRODUCT-LINEAGE`；bind **5/5**；lake e2e **3/3**；kernel **15/15**
- **后置**：UI-DTYPE-EDITOR；勿 publish `audio_nvh-v2`；勿 DataWorks

## 2026-08-20 — PLAT-DTYPE-LAKE-REUSE（跨会话复用已入库 Source）

- **用户问**：Lake Sources 是否仅会话可用？组 Sample 能否用以前上传的数据？
- **事实**：`put_source` 早已写 SQLite `platform_source` + 本地磁盘；**不是**会话临时数据
- **缺口**：UI 标题「本次会话」只持 React state；无 `GET /sources`，刷新后看不到历史源
- **修复**：`list_sources` + `GET /api/platform/sources`；Lake 页表格勾选多选组 Sample；刷新合并防竞态
- **验收**：`acceptance/PLAT-DTYPE-LAKE-REUSE.md`；`test_platform_datatype_lake.py` **6/6**；`platform-lake.spec.ts` **2/2**
- **未改**：taxonomy publish / AI-label / DataWorks

## 2026-08-20 — ISOLATE-DTYPE-CLIPS（OMS 总览隔离 hotfix）

- **用户 bug**：切到舱内 OMS/DMS 多模频道后仍能看到两条麦克风阵列 clip
- **根因**：`GET /api/clips?data_type_id=oms_cabin` 走未过滤的 `list_clips_light()`（全 `dim_clip`）；非 OMS 才走 `list_clips_light_for_data_type`
- **修复**：本地 light 列表按 active run 的 `pipeline_execution.data_type_id` 过滤——保留 NULL/空/`oms_cabin`/无 pe 行；排除 `audio_array_spec`/`ivi_ui_stub`；前端 cache bump `v3`
- **验收**：`acceptance/ISOLATE-DTYPE-CLIPS.md`；`test_audio_nvh_view.py` **5/5**
- **未改**：DataWorks / AI-label / timeline-replay

## 2026-08-20 — HMI-TIMELINE-REPLAY（时间轴重播）

- **问题**：Clip 播完停在末尾，无从头重播
- **修复**：`utils/playback.ts`（结束再播 → seek start）；舱内 `AudioWaveform`「重播」+ 空格；NVH `AudioNvhTimelinePanel` 同能力 + 空格
- **验收**：`acceptance/HMI-TIMELINE-REPLAY.md`；`scripts/playback.assert.mts` ok
- **未改**：deriver / recipe / DataWorks

## 2026-08-20 — PLAT-AUDIO-AI-LABEL（L6 语义 AI + draft 绑定）

- **用户问**：标签树建好了吗？音频也要 AI 打标
- **树状态**：`audio_nvh-v2` **draft** 78 叶，Taxonomy Hub 可见；**未 publish**（published 仍为 OMS `label_tree_baseline`）
- **AI**：`nvh_ai_label.fill_nvh_semantic_labels` 在 deriver 之后只写 `nvh.sem.*`；默认 `nvh_sem_heuristic`；可选 `nvh_sem_vl`（mel.png + DashScope，无 key 回退）
- **绑定**：`fact_clip_label.taxonomy_version_id` → draft v2 UUID（不调 `publish_version`）
- **配方**：`audio_array_spec.stages.label.enabled=true`
- **验收**：`acceptance/PLAT-AUDIO-AI-LABEL.md`；`test_nvh_ai_label.py` **5/5**；deriver **3/3**
- **约束**：勿 publish；勿 H-2；勿 DataWorks；勿 VL bbox

## 2026-08-20 — UI-NVH-OVERVIEW（纯音频 NVH 频谱时间轴 + typed 列表）

- **产品拍板**：总览 = typed clip 表（Leq / mel 缩略图）；探索/校核媒体 = **四通道 mel + SPL + 真实波形 + 共用 playhead**（非舱内四路、非 ASR）
- **根因修复**：`GET /api/clips?data_type_id=…` 对非 OMS 曾返回 `[]`；改走 `list_clips_light_for_data_type`
- **后端**：视图 `audio_nvh_timeline`；`GET .../audio-nvh`；配方 `overview_view` 切换（保留 `audio_spec_asr` 模板名）
- **前端**：`AudioNvhTimelinePanel`；`ClipMediaPanel` 自动探测；Explorer/Review 去 ASR 中心；Overview 隐藏 OMS 检索
- **前端增强**：NVH Explorer 详情标签轨由 raw `LabelRail` 改为 `ClipLabelTreeView`（舱内多模一致），并加入 `e2e/nvh-label-tree.spec.ts` 覆盖（`data-testid=audio-nvh-label-rail` 断言不存在）
- **验收**：`acceptance/UI-NVH-OVERVIEW.md`；`test_audio_nvh_view.py` **4/4**；`tsc -b`；`datatype-workspace.spec.ts` **1/1**；`nvh-label-tree.spec.ts` **1/1**
- **约束**：勿 publish `audio_nvh-v2`；语义写回另开 UI-NVH-REVIEW-SAVE；勿 H-2

## 2026-08-20 — OP-DERIVE-NVH（L2 → labels_json / y_json）

- **范围**：从 `audio_spec` + `head_meta` / `pcm_pa` 推导 audio_nvh-v2 **auto + semi 种子**；human / `ai_hypothesis` / `masking_band` 不写入
- **产物**：`hmi/backend/hmi/local/nvh_deriver.py`；`_run_audio_array_spec` 镜像成功后写 `fact_clip_label` + `platform_run.y_json`；`nvh_labels.json` + `audio_spec/derived/*`
- **约束**：`stages.label.enabled` 仍为 false；**不 publish** `audio_nvh-v2`
- **验收**：`acceptance/OP-DERIVE-NVH.md`；`test_nvh_deriver.py` **3/3**（含 CBK1 Leq∈[93,96]）

## 2026-08-20 — TAX-AUDIO-NVH-v2（声压/噪音真值标签全量 78 叶）

- **范围**：用户确认全量 v2（非 lite）。六维：元数据 / clip 声压·频域·时域 / 通道 / 频域明细 / 时域明细 / 通道间 proxy（非 DOA）/ 语义
- **产物**：`shared/config/audio_nvh_taxonomy.yaml`；节点定义 `hmi/backend/hmi/platform/audio_nvh_v2.py`
- **Seed**：启动时写入 draft `audio_nvh-v2`（78 节点）；**不 publish**，以免归档 OMS published
- **拍板**：分档 70/85/100 dB；语义 13 顶类；json_ref 相对 `runs/{run_id}/`；VL 关闭
- **验收**：`acceptance/TAX-AUDIO-NVH-v2.md`；`test_audio_nvh_v2.py` **3/3**；kernel 回归通过
- **下一步**：OP-DERIVE-NVH（L2 → labels_json）

## 2026-08-18 — PLAT-DTYPE-LAKE（源湖入库 UI + platform_run 编译）

- **源湖持久化**：`platform_source` 补 `content_hash` / `local_oss_key` / `local_path`；local 模式 `/api/platform/sources` 改为 persist-only 入湖，不提前建 `pipeline_run`
- **编译执行**：`local_sdk_worker` 新增 `platform_run` 认领/编译；复用 `platform_run.run_id` 作为 `pipeline_execution.run_id`；rosbag 各成 clip，video/audio/text 合并 raw_media，image 第一切片执行失败
- **平台状态**：`platform_run.status` 进入 `queued/running/completed/failed/labeled`；完成时从 `fact_clip_label` 最小聚合回写 `platform_run.y_json`
- **HMI**：新增 `/lake` 独立页面与侧栏入口；支持入湖、组 Sample、选 published DataType 预检并创建 `platform_run`
- **验收**：`acceptance/PLAT-DTYPE-LAKE.md`；`test_platform_datatype_lake.py` **5/5**；`test_platform_datatype_run.py` 回归通过；`tsc -b` 通过；`e2e/platform-lake.spec.ts` **1/1**
- **备注**：为跑通 Playwright，本地测试 admin 密码重置为 `admin123`

## 2026-08-18 — PLAT-DTYPE-RUN（管线开跑接到 DataType）

- **预检**：本地 `POST /api/pipeline/executions?data_type_id=` 先 `require_published_preflight`；失败 400 且带 `missing`，不入队
- **配方**：IVI 关 label/embed、强制 bbox opencv；OMS bbox 仍跟全局设置
- **持久化**：`pipeline_execution.data_type_id`；源湖 Sample + `platform_run`（y 按类型分文档）
- **HMI**：上传页必选数据类型；执行参数按配方灰显打标/向量
- **验收**：`acceptance/PLAT-DTYPE-RUN.md`；`test_platform_datatype_run.py` **8/8**；`tsc -b` 通过
- **下一步**：PLAT-DTYPE-LAKE；**HMI 在线 H-2 暂停不排期**

## 2026-08-18 — PLAT-DTYPE-KERNEL（平台数据类型内核）

- **内核**：算子目录 + 配方校验 + `oms_cabin` / `ivi_ui_stub` 种子；源/样本/Run SQLite；预检；产物缓存键
- **检索**：`data_type_id` 工作区隔离；IVI 不走 OMS 索引；缺省兼容 `oms_cabin`
- **HMI**：`/` 数据类型列表 → `/w/:dataTypeId` 总览
- **验收**：`acceptance/PLAT-DTYPE-KERNEL.md`；`test_platform_datatype_kernel.py` **15/15**；`tsc -b` 通过；**H-1 用户 2026-08-18 签字**
- **下一步**：继续平台内核（推荐 PLAT-DTYPE-RUN）；**HMI 在线 H-2 暂停不排期**

## 2026-08-14 — HMI-BBOX-OVERLAY（可编辑 jsonl 叠加）

- **后端**：`upsert_frame_boxes` 原子写 `bboxes.jsonl`；`PUT /api/clips/{id}/bboxes` + audit `clip.bboxes_upsert`（仅 local）
- **前端**：`BBoxOverlayLayer` 原图 letterbox 叠加；默认原图；「烧录预览」降级；暂停可拖/改角/删/双击新建；保存写回
- **接线**：Explorer `clipId/runId` + 侧栏选中联动；`e2e/bbox-overlay.spec.ts`
- **验收**：`acceptance/HMI-BBOX-OVERLAY.md`；`test_hmi_bbox_overlay.py` **2/2**
- **下一步仍推荐**：HMI 在线 H-2（未抢跑 M9.3 出口）

## 2026-08-12 — HMI-SDK-MODALITY（原始媒体 + Planner 模态门控）

- **Planner**：`source_manifest` / 显式模态 → 跳过 encode（成片）、ASR（无音频）、bbox/encode（无视频）；新增 `ingest_sources`（抽帧）
- **HMI**：管线管理暂存区支持 video/audio/text；本地落盘 `sources/…/source_manifest.json`；worker `plan_and_run`
- **验收**：`acceptance/HMI-SDK-MODALITY.md`；`tests.test_planner` 8/8；`test_source_upload_modality.py` 2/2
- **剩余**：云端原始媒体、多视频分 clip、Playwright；推荐下一步仍为 HMI 在线 H-2

## 2026-08-12 — HMI-SDK-BBOX OpenCV 5 Haar 修复

- **根因**：`opencv-python-headless` 5.0 的 `cv2/data` 无 cascade XML，且主包已移除 `CascadeClassifier`
- **修复**：`resolve_haar_cascade_path` 多路径 + env；打包 Haar XML + YuNet ONNX；cv2≥5 自动 `FaceDetectorYN`
- **验收**：`acceptance/HMI-SDK-BBOX.md` A-4；`unittest tests.test_bbox_capability` pass

## 2026-08-12 — HMI-SDK-BBOX（local-first）

- **管线参数**：`bbox_enabled` / `bbox_detector` / `bbox_element` / `encode_*` / YOLO 字段 → `BBOX_*`/`ENCODE_*`
- **Worker**：`local_sdk_worker` 改 `infer_full`（annotate_bbox + encode_preview）
- **预览**：SDK `cameras_bbox` + HMI `bbox_url`；Explorer Plain|BBox 切换
- **Taxonomy**：Hub `enum_tree` 编辑/展示；insights 叶子 id
- **验收**：`acceptance/HMI-SDK-BBOX.md`；`test_hmi_sdk_bbox.py` **5/5**
- **下一步仍推荐**：HMI 在线 H-2（未抢跑 M9.3 出口）

## 2026-08-11 — HMI 测试模式开关 + 重置测试数据

- **系统参数**：`HMI_TEST_MODE`（系统参数页 Switch）；关=强制云端、隐藏本地/云端切换与重置
- **重置**：文案「重置测试数据」；OSS 管理页（admin）+ 侧栏（测试模式）；云端清 OSS 前缀 + MC `aig_sdk__*`/`aig_rosbag__*`
- **验收**：`acceptance/HMI-TEST-MODE.md`；`test_test_mode_reset.py` 3/3

## 2026-08-10 — M9.3 hybrid DW 4-bag + meta repair · HMI 在线预备

- **Cloud E2E**：DataWorks hybrid 单 Driver（DPE extract+preview `dpe_parallel=4` + Driver MaxFrame AI asr/label/embed `ai_media_mode=oss_url`）4-bag；ds=`20260810`
- **验数**：clip1 `sha256:9a4ac3a…` / `bb319286-…` → `verify_sdk_v1_run.py` **18/18**
- **Meta**：Driver 写 `run.json`；dispatch top-level 取自 first item；`dim_clip` INSERT OVERWRITE upsert `active_run_id`；4 runs repair
- **进度**：CURRENT → 推荐 **HMI 在线**；M9.3 A-C 基本闭合、**H-2 pending**；`acceptance/M9.3.md` 更新
- **HMI**：设置已指向 `aig_sdk__` + bucket2；侧栏「在线」开关恢复；cloud overview/timeline 避开不存在的 v2 帧表

## 2026-08-05 — MaxFrame 2.8 content_part（SDK MC Omni/ASR）

- **SDK 0.3.2**：`mc/content_parts.py`；Omni **`cp.video`+`cp.audio`+`cp.text`（含 ASR）**；ASR Job2 `cp.audio`；`maxframe>=2.8.0`
- **Legacy**：`mf_ai_function.py` `ImageContentType.URL` + ASR content_part；rebundle job2/3/4 bundled
- **验数**：本机 `run_mc_oss_verify` → `mc_mode=omni_native` / `content_part_audio`；cloud **18/18**
- **文档**：`SDK.md` · `DATAWORKS_SDK.md` · runbook · `.env.example` · cursor rules
- **DPE 镜像重建**：`rosbag-sdk-dpe:0.3.2` + `pipeline/dist/rosbag-sdk-dpe-0.3.2.tar` + `dpe-sdk-image-pack-0.3.2.zip`（含新 wheel）

## 2026-08-03 — M9.3 原子 DataWorks 节点 + sdk_node_common

- **节点**：`sdk_extract_node` · `sdk_asr_node` · `sdk_preview_node` · `sdk_label_node` · `sdk_embed_node`
- **共享**：`pipeline/dataworks/sdk_node_common.py`（env 映射、RunContext、MC 校验）
- **重构**：`sdk_infer_node` / `sdk_asr_node` 复用 common；`DATAWORKS_SDK.md` 节点表
- **测试**：`test_sdk_atomic_nodes.py` + 既有 18 tests pass

## 2026-08-03 — M9.3 sdk_v1 cloud E2E 验数 + SDK MC 后端

- **SDK 0.3.1**：`MODEL_BACKEND=mc` MaxFrame 客户端骨架（`piplinesdk/oms_multimodal/mc/`）
- **DataWorks**：`sdk_infer_node.py` 接 `mc_odps_entry=o`、工作流参数映射、`client.close()`
- **验数**：`pipeline/scripts/verify_sdk_v1_run.py` · `test_verify_sdk_v1_m93.py`
- **文档**：`docs/sdk-v1-cloud-e2e-runbook.md` · `acceptance/M9.3.md`
- **CURRENT → M9.3 A-C 待 DataWorks**

## 2026-07-31 — M8.5 标签树裁剪（派生）

- **后端**：`dataset/taxonomy_crop.py`；derive `taxonomy_crop_label_ids` → 克隆 draft taxonomy + `export_label_ids`；assemble 导出 y 列过滤
- **UI**：`DatasetTaxonomyCropForm`；派生 Modal 区分「标签树裁剪」与「按标签值筛选 clip」
- **测试**：`test_dataset_m8.py` taxonomy crop case；E2E 文案更新

## 2026-07-31 — M8.5 派生向导 · 平衡 + 按标签筛选 clip

- **UI**：`DatasetDetailPage` 派生 Modal（父集条件、按标签筛选、类别平衡、实时预览）
- **工具**：`utils/datasetFilter.ts`（`buildDeriveFilterJson`）；`DatasetListPage` 复用
- **后端**：derive 部分 `filter_json` override merge（已有 `derive.py`）
- **测试**：`test_dataset_m8.py` 补 label crop derive；`e2e/dataset-derive-wizard.spec.ts`
- **验收**：`acceptance/M8.md` A-E2E-2/3

## 2026-07-31 — M10.10 Hub diff/impact/lineage UI

- **UI**：`TaxonomyLineageBar`、`TaxonomyVersionMetaPanel`；版本 Tab 血缘条；Drawer diff/impact；发布前 impact 确认框
- **API 客户端**：`getTaxonomyDiff`、`getTaxonomyImpact`；types 补全
- **E2E**：`e2e/taxonomy-hub.spec.ts` +2（lineage、diff panel）；**4 passed**
- **CURRENT → M7.5 全链 E2E / M9.3 待 DataWorks**

## 2026-07-31 — M9.2 docs + Dataset 创建向导 E2E 补全

- **M9.2**：`docs/postgresql-migration-path.md`；`acceptance/M9.2.md`；tracking M9.2 → done
- **E2E**：`e2e/dataset-create-wizard.spec.ts`（M7.8 导出建议+采用；M7.5 Parquet checkbox；M8 平衡维度 UI）
- **CURRENT → M9.3 H-1 / M7.5 全链 E2E**

## 2026-07-31 — M10 出口 · Taxonomy 语义中枢

- **API**：context、coverage、diff、impact、lineage、proposals；dataset preview `taxonomy_version_distribution`
- **UI**：Hub Tabs（版本/数据洞察/提案）、TaxonomyContextBar、Dataset Taxonomy 契约锁定、Similar 提案入口
- **DB**：`taxonomy_proposal`；R11–R15 落地
- 验收：`test_taxonomy_m10.py` + `e2e/taxonomy-hub.spec.ts` + `npm run build`；`acceptance/M10.md`
- **CURRENT → M9.3 / 维护**

## 2026-07-31 — M10 立项 · Taxonomy 语义中枢

- **DOC-M10**：`docs/m10-implementation-notes.md`（Hub + 全链路契约 + 覆盖率 + diff/impact + 提案）
- **缺口 R11–R15** 写回 `docs/prd-rosbag-labels.md` §13
- **阶段 U**：`docs/design/m10-ui-options.md`（推荐 A−+B）；`DESIGN-M10.md` 待用户确认
- tracking：M10-U、M10.1–M10.9；**CURRENT → M10-U**
- 舱内场景挖掘：M10 只做洞察+提案 ingest（R14）；重算法离线

## 2026-07-31 — M7.8 出口 · 导出顾问

- `export_advisor.py`：按 clip/行数/标签列/embedding 给出 preset、Parquet、取样建议
- `POST /api/datasets/preview` → `export_recommendation`；创建向导「导出建议」+「采用建议」
- 验收：`test_export_advisor_m78.py` + `npm run build`；`acceptance/M7.8.md`

## 2026-07-31 — M7.5 出口 · Parquet 可选导出

- `parquet_export.py`：X/y Parquet + OSS + zip 打包
- `filter_json.include_parquet`；创建向导 Checkbox；meta `parquet_available`
- 验收：`test_dataset_m75.py` + `npm run build`；`acceptance/M7.5.md`
- 依赖：`pyarrow` 加入 `hmi/backend/requirements.txt`

## 2026-07-31 — M9 出口 · 部署与治理

- **M9.1**：`GET /api/admin/audit`（admin-only）；`query_audit_logs` + `actor_username`
- **M9.4**：`taxonomy_hint.py`；dataset preview/detail R10 警告；列表/详情 Alert
- **M9.5**：`AdminAuditPage` + `/admin/audit` 菜单 + `listAuditLogs`
- 验收：`test_audit_m9.py` + `npm run build` 全绿；`acceptance/M9.md`
- **M9.2 PostgreSQL / M9.3 cloud E2E** 延期（docs / H-1）
- **CURRENT → 维护 / 可选 M7.5**

## 2026-07-30 — M6–M8 出口 · 治理链收敛

- **M6**：删旧 ReviewQueue/Detail；`test_review_v2.py` + `e2e/review-v2.spec.ts` + `acceptance/M6.md`
- **M7**：Schema/build 报告/export preset；`test_dataset_m7.py`；前端 dataset UI
- **M8**：balance/oversample/recipe/derive；`test_dataset_m8.py`；examples/
- 回归：`test_prd_appendix_c.py` 全绿（legacy reviewed + OSS mock 修复）
- **CURRENT → M9 预告**

## 2026-07-30 — M8 立项 · Dataset 样本扩展

- 边界确认：平台 = 平衡采样 / 过采样 / recipe 契约 / 派生 lineage；训练侧 = transform 执行
- `docs/m8-implementation-notes.md` + `docs/dataset-augmentation-recipe-schema.md`
- tracking M8.1–M8.7；`acceptance/M8.md`；delivery schema → 1.1 预告
- **依赖 M7 出口**；M9 预留部署/audit

## 2026-07-30 — M7 立项 · Dataset 交付加固

- 产品边界确认：不做 PyTorch 开箱即用；强化 Schema 契约、build 报告、export preset
- `docs/m7-implementation-notes.md` + `docs/dataset-delivery-schema.md` v1.0 草案
- tracking M7.1–M7.7；`acceptance/M7.md` 模板
- **CURRENT**：M6.6 仍为推荐工单；M6 出口后启动 M7

## 2026-07-23 — M6.3 完成 · submit + audit

- POST `/api/review/v2/submit`：confirm/correct/uncertain → merge + rollup
- audit `clip.label_field_review`；rollup 时 OSS export
- reopen 时清空 field reviews
- `test_review_m63.py` 全绿
- **CURRENT → M6.4**

## 2026-07-23 — M6.2 完成 · v2 task queue API

- `v2_tasks.py`：AI 分歧排序（空值优先）+ 全面校核 AI 值匹配
- `v2_router.py`：`/api/review/v2/next|prev|session|tasks/stats|label-options|tasks`
- 会话内 `prev` 历史栈（按 user_id）
- `test_review_m62.py` 全绿
- **CURRENT → M6.3**

## 2026-07-23 — M6.1 完成 · field review DB + merge

- `clip_label_field_review` 表 + `field_review_db.py`
- `merge.py`：`apply_field_review` 合并 labels_json + rollup reviewed
- `test_review_m61.py` 全绿；`acceptance/M6.1.md`
- **CURRENT → M6.2**

## 2026-07-23 — M6 立项 · 校核页 v2

- 用户澄清：逐标签粒度、双模式（AI 分歧 / 全面校核）、单页替换旧 UI
- `docs/prd-review-v2.md` 增补 + 缺口评审 P0=0
- `docs/m6-implementation-notes.md` + tracking M6.1–M6.6
- **CURRENT → M6.1**

## 2026-07-21 — M5 里程碑出口

- `test_prd_appendix_c.py`：附录 C C1–C8、N1–N6 全绿
- WIKI §8/§9 路由与 API 表更新
- `acceptance/M5.md` 全绿
- **PRD P0 能力闭环**

## 2026-07-21 — M4 里程碑出口

- `test_dataset_m4.py` 全绿；m41–m45 spot 回归
- `acceptance/M4.md` 全绿
- **M4 done** → 可开 M5

## 2026-07-21 — M4.6 完成

- `DatasetListPage` / `DatasetDetailPage`、侧栏「数据集」
- `e2e/datasets-admin.spec.ts`；`npm.cmd run build` 全绿
- **CURRENT → M4.7**

## 2026-07-21 — M4.5 完成

- `dataset/router.py`、`require_dataset_read/manager`、audit
- `test_dataset_m45.py` 全绿
- **CURRENT → M4.6**

## 2026-07-21 — M4.4 完成

- `dataset/mc_export.py`、`migrate_dataset_snapshot_row.sql`；build cloud 挂钩
- `test_dataset_m44.py` 全绿
- **CURRENT → M4.5**

## 2026-07-21 — M4.3 完成

- `dataset/build.py`、`export.py`、`hmi/scripts/build_dataset_snapshot.py`
- `test_dataset_m43.py` 全绿
- **CURRENT → M4.4**

## 2026-07-21 — M4.2 完成

- `dataset/assemble.py`（R7/R8 过滤 + X/y）；`test_dataset_m42.py` 全绿
- **CURRENT → M4.3**

## 2026-07-21 — M4.1 完成

- `dataset_db.py`；`test_dataset_m41.py` 全绿
- **CURRENT → M4.2**

## 2026-07-21 — DOC-M4 完成

- `docs/m4-implementation-notes.md` v1.0；工单 M4.1–M4.7 入 tracking
- **CURRENT 推荐 → M4.1**（Dataset DB + dataset_db.py）

## 2026-07-21 — M3 里程碑出口

- `test_review_m3.py` 全绿（S3/C3/C4/N5/N6）
- `acceptance/M3.md` 全绿；子脚本 m31–m34 回归通过
- **M3 done** → 可开 DOC-M4 / M4

## 2026-07-21 — M3.5 完成

- `/review` 队列 + 详情页；侧栏「校核」；409 冲突提示
- `frontend/e2e/review-admin.spec.ts`；`npm run build` 全绿
- **CURRENT → M3.6**

## 2026-07-21 — M3.4 完成

- save → `clip.review`；reopen → `clip.reopen`；409 不写 audit
- `test_review_m34.py` 全绿
- **CURRENT → M3.5**

## 2026-07-21 — M3.3 完成

- `/api/review/*`（queue / detail / save / reopen / enqueue）
- `require_reviewer` 门禁；`test_review_m33.py` 全绿
- **CURRENT → M3.4**

## 2026-07-21 — M3.2 完成

- `review/aggregate.py`（R4 聚合）、`review/enqueue.py`、`hmi/scripts/enqueue_review_clips.py`
- `test_review_m32.py` 全绿
- **CURRENT → M3.3**

## 2026-07-21 — M3.1 完成

- `review_db.py`、`audit.py`；`test_review_m31.py` 全绿
- **CURRENT → M3.2**

## 2026-07-21 — DOC-M3 完成

- `docs/m3-implementation-notes.md` v1.0；工单 M3.1–M3.6 入 tracking
- **CURRENT 推荐 → M3.1**（Review DB + audit_log）

## 2026-07-21 — M2.7 / M2 里程碑出口

- `test_taxonomy_m2.py` 出口集成全绿；`acceptance/M2.md` + `M2.7.md`
- 回归 m22/m24/m26 + frontend build
- **M2 milestone done**；**CURRENT → DOC-M3**

## 2026-07-21 — M2.6 完成

- `taxonomy/export.py` publish → OSS YAML + latest.json + dispatch merge + app_meta
- `pipeline_dispatch.attach_taxonomy_to_dispatch_payload`；job0_dispatch 集成
- `sql/maxcompute/migrate_fact_image_label_taxonomy.sql`；`test_taxonomy_m26.py` 全绿
- **CURRENT → M2.7**

## 2026-07-21 — M2.5 完成

- `TaxonomyPage.tsx` + `/taxonomy` 路由；admin 侧栏「标签树」
- Playwright `e2e/taxonomy-admin.spec.ts`；frontend build 通过
- **CURRENT → M2.6**

## 2026-07-21 — M2.4 完成

- `taxonomy/compat.py`；`GET /api/label-taxonomy` 默认 published + YAML fallback
- 可选 `?version_id=` 预览；`test_taxonomy_m24.py` 全绿
- **CURRENT → M2.5**

## 2026-07-21 — M2.3 完成

- `hmi/backend/hmi/taxonomy/router.py`；`/api/taxonomy/*`（versions/tree/nodes/publish/archive/clone）
- `archive_version` / `clone_version`；`test_taxonomy_m23.py` 全绿
- **CURRENT → M2.4**

## 2026-07-21 — M2.2 完成

- `taxonomy_import.py`、`hmi/scripts/import_taxonomy_yaml.py`；`publish_version()` 入 taxonomy_db
- `test_taxonomy_m22.py` 通过；CLI 导入 v2 draft 68 nodes，二次 skip
- **CURRENT → M2.3**

## 2026-07-21 — M2.1 完成

- `taxonomy_db.py` + schema；`test_taxonomy_m21.py` 通过
- **CURRENT → M2.2**

## 2026-07-21 — DOC-M2 完成

- `docs/m2-implementation-notes.md` v1.0；工单 M2.1–M2.7 入 tracking
- **CURRENT 推荐 → M2.1**（Taxonomy DB schema）

## 2026-07-21 — M1.5 / M1 里程碑出口

- `test_auth_m1_exit.py` 覆盖 C1/C8/N1/N2；M1.1–M1.4 回归全通过
- `acceptance/M1.md`；WIKI §8.1 更新
- **M1 done**；**CURRENT 推荐 → DOC-M2**

## 2026-07-21 — M1.4 完成

- RequireRole、AdminUsersPage、角色菜单；OSS API 后端 ACL
- test_auth_m14.py + frontend build 通过
- **CURRENT 推荐工单 → M1.5**

## 2026-07-21 — M1.3 完成

- 前端 LoginPage、AuthContext、RequireAuth、axios http 客户端
- 现有 API 调用改走 authenticated http；build 通过
- **CURRENT 推荐工单 → M1.4**

## 2026-07-21 — M1.2 完成

- Admin API：`GET/POST/PATCH /api/admin/users` + `require_admin`
- `hmi/scripts/bootstrap_admin.py`；`hmi/backend/scripts/test_auth_m12.py` 全通过
- **CURRENT 推荐工单 → M1.3**

## 2026-07-21 — M1.1 完成

- 实现 `app_db.py`、`auth/`（JWT + middleware + login/me/logout/refresh）
- `main.py` 挂载 AuthMiddleware 与 auth router
- 自动化：`hmi/backend/scripts/test_auth_m11.py` 全通过
- **CURRENT 推荐工单 → M1.2**

## 2026-07-21 — 阶段 E/F Bootstrap

- 创建 `project-management/` 全套（CURRENT、tracking、board、milestones、acceptance 模板）
- 创建 `docs/m1-implementation-notes.md` v1.0，拆 M1.1–M1.5
- 创建 `.cursor/rules/project-progress-handoff.mdc`、`AGENTS.md`

## 2026-07-21 — 阶段 A–B / D

- 用户确认 4 项新能力澄清
- 产出 `docs/prd-rosbag-labels.md` v0.2，P0=0
