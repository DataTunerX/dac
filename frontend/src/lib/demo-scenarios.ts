export type DemoScenarioStatus = "ready" | "partial" | "blocked"
export type DemoStepKind = "chat" | "navigate" | "blocked"

export interface DemoStep {
  id: string
  scenarioId: string
  title: string
  kind: DemoStepKind
  purpose: string
  expected: readonly string[]
  estimatedTime: string
  prompt?: string
  href?: string
  caution?: string
  blockedReason?: string
}

export interface DemoScenario {
  id: string
  label: string
  title: string
  purpose: string
  status: DemoScenarioStatus
  steps: readonly DemoStep[]
}

const jadePrompt =
  "汉代玉器：身体、死亡与身份。请分别说明以下四部分：（1）本馆汉代玉蝉、玉衣片、玉璧的馆藏登记事实；（2）同类汉墓玉器的考古学证据；（3）秦汉丧葬礼制中饭含与玉衣制度的历史文献依据；（4）死者祭拜与家族纽带、集体记忆的人类学与社会学解释。"

const ceramicsPrompt =
  "请严格依类型学层级回答：闽江流域出土宋元酱釉瓷器的“型、亚型、式”分别以哪些形态变量建立？逐项列出口部、腹部、足/底部、装饰或工艺特征，并给出对应出土单位；不要用现代常识补充，也不要把其他釉色器类混入。"

const newArtifactPrompt =
  '给wwybsj展品录入新展品，信息如下：{ "ww_bh_leixing": "藏品总登记号", "ww_bianhao": "472", "ww_mingchen": "唐鎏金舞马衔杯纹银壶", "ww_yuanming": "舞马衔杯银壶", "ww_niandai_a": "中国历史学年代", "ww_niandai_b": "唐(618~907)", "ww_niandai_c": "盛唐", "ww_niandai_jt": "约公元8世纪", "ww_leibie": "金银器", "ww_zhidi_a": "复合质地", "ww_zhidi_b": "无机质", "ww_zhidi_c": "银、金", "ww_shuliang": 1, "ww_gao": "14.80", "ww_chicun": "高14.8厘米 口径2.3厘米", "ww_zhiliang_jt": "0.549", "ww_zhiliang_dw": "kg", "ww_jibie": "一级", "ww_laiyuan": "1970年陕西省西安市何家村唐代窖藏出土", "ww_wancan_cd": "完整", "ww_wancan_zk": "壶身鎏金舞马纹清晰，提梁与壶盖以银链相连", "ww_baocun_zt": "状态稳定，不需修复", "ww_mingchen_en": "Tang Gilt Silver Flask with Dancing Horse Motif", "ww_ctime": "2026-09-02 10:00:00" }'

export const DEMO_SCENARIOS: readonly DemoScenario[] = [
  {
    id: "scenario-1-1",
    label: "场景 1.1",
    title: "确定性事实与 DAC 证据纠错",
    purpose: "验证领域路由、具体证据和错误数据纠正；直接 LLM 对照需在独立模型窗口运行。",
    status: "partial",
    steps: [
      {
        id: "1-1-a",
        scenarioId: "scenario-1-1",
        title: "莫高窟 130 窟供养人像",
        kind: "chat",
        purpose: "检查回答是否从泛泛的风格判断深入到具体图像和中国化证据。",
        estimatedTime: "1–2 分钟",
        prompt: "为什么莫高窟第 130 窟晋昌郡都督一家供养人像，不能只看作普通的功德肖像，而应看作唐代佛教绘画中国化的证据？",
        expected: ["说明第 130 窟与张萱同时代", "联系中原仕女画、周家样与佛教艺术中国化", "至少给出一项供养人像的具体视觉细节", "展开思考过程可查看路由与证据来源"],
        caution: "本窗口执行 DAC 查询。直接 LLM 基线需要在独立模型窗口用同一提示词运行。",
      },
      {
        id: "1-1-b",
        scenarioId: "scenario-1-1",
        title: "王公淑墓《牡丹芦雁图》",
        kind: "chat",
        purpose: "检查回答是否用尺寸、构图和传承关系支撑艺术史判断。",
        estimatedTime: "1–2 分钟",
        prompt: "北京海淀八里庄王公淑墓出土的唐代《牡丹芦雁图》，为什么不能只说成“墓葬装饰花鸟画”，而应看成唐代花鸟画成熟及后世厅堂花鸟传统的关键证据？",
        expected: ["出现王公淑墓、《牡丹芦雁图》和 156 × 290 cm", "描述牡丹、芦雁、蜀葵/百合及对称丰满构图", "联系边鸾或边鸾传派", "联系徐熙装堂花/铺殿花传统"],
      },
      {
        id: "1-1-c",
        scenarioId: "scenario-1-1",
        title: "冻融石环数据纠错",
        kind: "chat",
        purpose: "验证系统会根据来源纠正问题中的错误数字，而不是顺着错误前提回答。",
        estimatedTime: "1–2 分钟",
        prompt: "判断题：在多年冻土区石环形成过程中，砾石因冻融作用被顶托到地面后，其水平迁移主要发生在活动层上部地表；祁连山平顶冰川边缘的观测说明冰川退缩两年后冰碛物中可形成大量石环，而大雪山地下 2 cm 埋石实验则显示石块一个月后被顶托到地面并侧向移动 3-8 cm。若按一年只有 3 个月活动期计算，该实验对应的年移动量为 9-24 cm/a，略快于巴伦支海斯匹次卑尔根群岛观测到的 5-10 cm/a。",
        expected: ["判定题干数据有误", "原始侧向移动应为 2–5 cm", "年化应为 6–15 cm/a，而不是 9–24 cm/a", "提供证据来源或出处"],
      },
    ],
  },
  {
    id: "scenario-1-2",
    label: "场景 1.2",
    title: "多 DAC 综合回答与证据分级",
    purpose: "逐题检查馆藏事实、跨域协作、证据强度和解释边界。",
    status: "ready",
    steps: [
      {
        id: "1-2-1",
        scenarioId: "scenario-1-2",
        title: "汉代玉器：四 DAC 协作",
        kind: "chat",
        purpose: "用四个明确子问题触发馆藏、考古、历史和人类学 DAC 并行协作。",
        estimatedTime: "约 4 分钟",
        prompt: jadePrompt,
        expected: ["路由显示 multi_root、needs_split=true、任务数=4", "准确使用 0349、0265、0394、0244 馆藏记录", "分开登记事实、墓葬比较、礼制文本和社会解释", "不把推测的身份或使用方式写成事实"],
        caution: "四个编号部分和“请分别说明”是触发拆分的关键，请勿改写。",
      },
      {
        id: "1-2-2",
        scenarioId: "scenario-1-2",
        title: "渤海建筑构件",
        kind: "chat",
        purpose: "评估佛教建筑空间、工匠技术与政权文化表达的证据边界。",
        estimatedTime: "1–3 分钟",
        prompt: "请以本馆渤海三彩建筑构件、佛像装饰、莲座、板瓦、筒瓦等材料为基础，评估它们能否构成一个关于渤海佛教建筑空间、工匠技术与政权文化表达的研究专题。哪些判断可以由馆藏支持，哪些只能来自同类遗址和建筑史比较？",
        expected: ["区分本馆馆藏支持与同类遗址比较", "标记佛教空间和政权表达的推断强度", "提供馆藏登记号或来源"],
      },
      {
        id: "1-2-3",
        scenarioId: "scenario-1-2",
        title: "新罗莲花纹瓦当",
        kind: "chat",
        purpose: "测试跨区域视觉语汇传播与地方化解释是否保持证据克制。",
        estimatedTime: "1–3 分钟",
        prompt: "本馆有一批新罗莲花纹瓦当。请讨论这些建筑构件如何用于研究佛教建筑装饰、工匠标准化、东亚视觉语汇传播与地方化。回答应说明：仅凭瓦当纹饰能说到什么程度，不能直接推出什么传播路线或寺院功能。",
        expected: ["说明纹饰可支持的观察", "不从纹饰直接推出传播路线或寺院功能", "注明本地与比较材料来源"],
      },
      {
        id: "1-2-4",
        scenarioId: "scenario-1-2",
        title: "宋代瓷器与消费",
        kind: "chat",
        purpose: "区分地方馆藏观察和需要窑址、沉船、墓葬或贸易网络补强的判断。",
        estimatedTime: "1–3 分钟",
        prompt: "请以本馆宋代青白釉瓷碗、白釉刻划花瓷碗、青釉莲瓣纹瓷碗、魂瓶等为材料，讨论宋代陶瓷如何反映生产技术、市场流通、日常消费与丧葬/礼俗需求之间的关系。哪些可以作为地方馆藏的材料观察，哪些需要窑址、沉船、墓葬或贸易网络证据补强？",
        expected: ["准确引用馆藏器物", "明确指出外部证据缺口", "不把市场流通和用途推断写成登记事实"],
      },
      {
        id: "1-2-5",
        scenarioId: "scenario-1-2",
        title: "高句丽铁器",
        kind: "chat",
        purpose: "检查器物功能、使用痕迹、身份和军事化解释的证据等级。",
        estimatedTime: "1–3 分钟",
        prompt: "请以本馆高句丽铁斧、铁带钩等铁器为基础，讨论铁器如何帮助研究高句丽社会中的生产活动、武备、身份标识与区域资源利用。请特别区分器物功能推测、使用痕迹证据、社会身份判断和军事化解释之间的证据等级。",
        expected: ["分级呈现功能推测与使用痕迹", "不从器名直接推出身份", "军事化解释有独立证据支撑或明确保留"],
      },
      {
        id: "1-2-6",
        scenarioId: "scenario-1-2",
        title: "金宋明铜镜",
        kind: "chat",
        purpose: "测试图像、铭文、祝福语和社会记忆解释的边界。",
        estimatedTime: "1–3 分钟",
        prompt: "请比较本馆金代四兽铜镜、十二生肖铜镜、双鱼纹铜镜、宋代故事铜镜、明代吉语铜镜等材料，讨论铜镜如何从日常器物转化为图像叙事、祝福语、身份表达与社会记忆的媒介。回答应说明纹饰/铭文能支持的解释边界。",
        expected: ["比较多个时代和纹饰类型", "区分可读铭文/纹饰与社会解释", "避免无证据的身份归属"],
      },
      {
        id: "1-2-7",
        scenarioId: "scenario-1-2",
        title: "长时段玉器",
        kind: "chat",
        purpose: "检查长时段延续/断裂论述是否区分类型年代观察和外部验证。",
        estimatedTime: "1–3 分钟",
        prompt: "从商周、战国、汉到清代，本馆玉器数量较多。请以玉璧、玉蝉、玉佩、带钩、玉戈、玉饰件为线索，讨论“玉作为身份与身体技术”的长时段变化。哪些变化可以从馆藏类型和年代分布观察，哪些必须依靠墓葬等级、使用位置、文本制度和材料来源来验证？",
        expected: ["覆盖类型与年代分布", "把墓葬等级、使用位置和制度文本列为验证项", "不从器物名称直接推断精英身份"],
      },
    ],
  },
  {
    id: "scenario-2",
    label: "场景 2",
    title: "文本入库改变 DAC 知识",
    purpose: "用完全相同的问题验证新论文入库前后回答发生可归因的变化。",
    status: "partial",
    steps: [
      {
        id: "2-before",
        scenarioId: "scenario-2",
        title: "入库前基线查询",
        kind: "chat",
        purpose: "记录 DAC 在没有目标论文时的知识边界。",
        estimatedTime: "约 1 分钟",
        prompt: ceramicsPrompt,
        expected: ["无法回答或明确说明来源不可用", "不使用常识补齐型、亚型、式细节"],
      },
      {
        id: "2-ingest",
        scenarioId: "scenario-2",
        title: "打开 TDB 入库流水线",
        kind: "navigate",
        purpose: "在新标签页将《闽江流域出土宋元瓷器初步研究》写入隔离测试库。",
        estimatedTime: "数分钟",
        href: "/tdb-pipeline",
        expected: ["目标选择“考古学（论文测试库，隔离）” (:8996)", "使用一个尚未入库的新 S3/MinIO 前缀", "等待任务成功并确认 chunk、ontology、wiki/data 层更新"],
        caution: "不要使用生产考古库 :8989。必须先准备包含目标论文的全新 S3 前缀；完成入库后再回到本页点击下一步。",
      },
    ],
  },
  {
    id: "scenario-3",
    label: "场景 3",
    title: "新增文物并扩展本地 TDB",
    purpose: "证明一条新登记记录可被关系化、关联远程考古知识并立即查询。",
    status: "partial",
    steps: [
      {
        id: "3-build",
        scenarioId: "scenario-3",
        title: "写入 新藏品",
        kind: "chat",
        purpose: "调用 wwybsj build agent 写入登记事实、对齐术语并建立关联。",
        estimatedTime: "约 2 分钟",
        prompt: newArtifactPrompt,
        expected: ["路由至 Wwybsj-Build-TDB-Agent", "报告 L0 登记事实写入", "报告 L1 术语对齐或关系 enrichment", "保留新事实的来源"],
        caution: "此步骤会修改 live wwybsj TDB，登记号只能使用一次。点击运行即表示确认执行该写入。",
      },
      {
        id: "3-after",
        scenarioId: "scenario-3",
        title: "查询新藏品文化价值",
        kind: "chat",
        purpose: "验证回答同时使用新本地记录和远程考古关系。",
        estimatedTime: "约 1 分钟",
        prompt: "第472号展品的文化价值是什么？",
        expected: ["找到 472 号藏品", "引用唐代金银器、何家村窖藏和舞马纹相关知识", "区分本地登记事实与外部考古知识", "不增加无来源属性"],
      },
    ],
  },
  {
    id: "scenario-4",
    label: "场景 4",
    title: "生成并部署馆藏物标 DAC",
    purpose: "让平台创建技能和 Agent，加入路由后完成一次馆藏物标生成。",
    status: "partial",
    steps: [
      {
        id: "4-generate",
        scenarioId: "scenario-4",
        title: "生成馆藏物标服务",
        kind: "chat",
        purpose: "请求 Appgen 编写技能、发布并部署新的 DAC。",
        estimatedTime: "2–3 分钟",
        prompt: "开发部署一个新的服务，能够根据馆藏的要求产生馆藏物标（label）。物标需要包含：藏品名称、年代、质地、尺寸、登记号，以及一段面向观众的说明文字。",
        expected: ["路由至 Appgen-Agent", "技能发布到 skill hub", "创建并部署新的 DataAgentContainer", "返回新 Agent 名称"],
        caution: "此步骤会在 live 集群创建技能与 Agent 资源。",
      },
      {
        id: "4-agents",
        scenarioId: "scenario-4",
        title: "在智能体页面确认部署",
        kind: "navigate",
        purpose: "新标签页打开智能体列表，检查新 skill DAC 已就绪。",
        estimatedTime: "约 1 分钟",
        href: "/agents",
        expected: ["关闭“业务智能体”类型过滤", "在 default 命名空间找到生成的 skill DAC", "状态为可用/运行中"],
        caution: "完成检查后回到本页，再点击下一步。",
      },
      {
        id: "4-use",
        scenarioId: "scenario-4",
        title: "使用新 DAC 生成物标",
        kind: "chat",
        purpose: "验证路由器会选择刚生成的能力并调用馆藏知识。",
        estimatedTime: "约 1 分钟",
        prompt: "给006号藏品写一个馆藏物标",
        expected: ["路由选择新生成的馆藏物标 DAC", "输出包含名称、年代、质地、尺寸、登记号和观众说明", "馆藏事实准确且服务调用 trace 可见"],
      },
    ],
  },
  {
    id: "scenario-5",
    label: "场景 5",
    title: "存储 HLD 与竞品分析",
    purpose: "从 RFI/需求生成 HLD 或针对性竞品报告。",
    status: "blocked",
    steps: [
      {
        id: "5-hld",
        scenarioId: "scenario-5",
        title: "根据 RFI 生成 HLD",
        kind: "blocked",
        purpose: "生成约 10 页、包含架构和设计决策的高层设计文档。",
        estimatedTime: "阻塞",
        expected: ["读取指定 RFI/requirements", "产生多页 HLD artifact", "返回 S3 或下载位置"],
        blockedReason: "当前平台没有存储领域语料、RFI 输入、HLD 技能或对应 DAC。",
      },
      {
        id: "5-competitive",
        scenarioId: "scenario-5",
        title: "存储产品竞品分析",
        kind: "blocked",
        purpose: "比较 Dorado 8000、HDS VSP 5000 和 PowerMax 8500，并映射 RFI 需求。",
        estimatedTime: "阻塞",
        expected: ["结构化比较关键维度", "Plus 版抽取并映射 RFI 要求", "产出针对性报告"],
        blockedReason: "当前平台没有存储语料或适用技能；已知运行会以 no_suitable_skill 结束。",
      },
    ],
  },
  {
    id: "scenario-6",
    label: "场景 6",
    title: "建筑平面图理解",
    purpose: "把图纸 A01 转为可查询的房间结构并统计卧室。",
    status: "blocked",
    steps: [
      {
        id: "6-bedroom",
        scenarioId: "scenario-6",
        title: "统计 A01 卧室",
        kind: "blocked",
        purpose: "根据已入库图纸回答卧室数量和位置。",
        estimatedTime: "阻塞",
        expected: ["识别图纸 A01", "返回卧室数并列出位置/标签证据", "不使用通用建筑常识猜测"],
        blockedReason: "尚未加载建筑图纸，也没有从图像抽取房间实体的视觉/结构化管线和技能。",
      },
    ],
  },
  {
    id: "scenario-7",
    label: "场景 7",
    title: "电路板图理解",
    purpose: "从 2 号电路图抽取元件并识别尺寸最大的芯片。",
    status: "blocked",
    steps: [
      {
        id: "7-chip",
        scenarioId: "scenario-7",
        title: "识别最大芯片",
        kind: "blocked",
        purpose: "基于已入库板图/网表回答，而不是依赖通用电子知识。",
        estimatedTime: "阻塞",
        expected: ["识别电路图 2", "给出元件标号和尺寸/边界框证据", "答案来自已抽取板级数据"],
        blockedReason: "尚未加载板图或网表，也没有元件检测、尺寸抽取及查询技能。",
      },
    ],
  },
]

export const DEMO_STEPS: readonly DemoStep[] = DEMO_SCENARIOS.flatMap((scenario) => scenario.steps)

export function getDemoStepIndex(stepId: string): number {
  return DEMO_STEPS.findIndex((step) => step.id === stepId)
}

export function getScenarioForStep(step: DemoStep): DemoScenario {
  const scenario = DEMO_SCENARIOS.find((item) => item.id === step.scenarioId)
  if (!scenario) throw new Error(`Unknown demo scenario: ${step.scenarioId}`)
  return scenario
}
