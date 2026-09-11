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

const unifiedNasPrompt = `项目采用名称“某大型制造/科研集团｜企业级统一 NAS 平台建设”，评估 Huawei 与 NetApp，输出 DOCX。

客户是一家大型制造/科研集团，现有多个数据中心，需要建设一套企业级统一 NAS 平台，承载研发、办公文件、虚拟化、容器、AI、数据分析和备份等业务。现有环境包含 Dell/HP 服务器、VMware、Red Hat、Windows、Kubernetes 以及部分 AWS/Azure 公有云资源。

初始有效数据约 3 PB，预计三年增长到 8–10 PB。要求系统能够横向扩展，并尽量避免扩容过程中进行大规模数据迁移。

协议、身份与多租户要求：NFS v3 / NFS v4.1、SMB 2.x / SMB 3.x、NFS 和 SMB 同一文件系统访问、POSIX ACL、Windows ACL、Kerberos、LDAP、Microsoft Active Directory、DNS / NTP、IPv4 / IPv6、多租户 Namespace。不同部门须具备独立容量、性能、权限和网络隔离；单文件系统至少扩展到数 PB，单 Namespace 可容纳数十亿文件。

Windows 文件服务：约 15,000 名 Windows 用户，大量 Office、设计文档和共享文件。NAS 必须原生加入 Microsoft Active Directory，并支持 AD Domain Join、SMB ACL、NTFS 风格权限、SID、AD Group、Kerberos Authentication、SMB Signing、SMB Encryption、Access Based Enumeration、DFS Namespace、Windows Previous Versions、Microsoft VSS、文件锁、Quota 和用户/组容量限制。Windows 用户不建立独立 NAS 用户体系，权限直接由 AD Security Group 控制。示例路径：\\\\corp.example.com\\rd、\\\\corp.example.com\\finance、\\\\corp.example.com\\design。

Linux 与计算集群：研发和仿真服务器运行 RHEL、Rocky Linux、Ubuntu、SUSE；必须支持标准 Linux NFS client，无需专有客户端。约 1,000 节点计算集群，典型负载包括 EDA、CAE、CFD、Genome Analysis、Simulation、Software Build、Log Analysis。要求 NFSv3/v4.1、优先 pNFS、优先 RDMA/NFS over RDMA、高并发 metadata、大量小文件、大文件顺序 IO、POSIX locking、UID/GID mapping。性能目标：Sequential Read >= 100 GB/s；Sequential Write >= 50 GB/s；Random Read IOPS >= 1,000,000 IOPS；File create >= 300K ops/s；File stat >= 1M ops/s。

VMware：现有约 4,000 台 VMware VM。存储须作为 VMware NFS Datastore，并最好取得 VMware 官方兼容认证。支持 ESXi、vCenter、NFS Datastore、VMware HA、DRS、vMotion、Storage vMotion、VMware Snapshot、Site Recovery Manager；希望支持 VAAI NAS，包括 File Clone、Fast File Clone、Space Reservation、Extended Statistics。通过 NAS snapshot/clone 快速创建大量开发测试 VM。

容器：平台包括 Kubernetes、Red Hat OpenShift、Rancher、VMware Tanzu。NAS 必须支持 CSI Driver、Dynamic Provisioning、PersistentVolume、PersistentVolumeClaim、ReadWriteMany、Snapshot API、Volume Clone、Volume Expansion；多个 Pod 可同时挂载共享 volume。StorageClass 可指定 Performance Tier、Quota、Snapshot Policy、Replication Policy、Tenant、QoS。优选 Kubernetes Operator 管理 NAS 生命周期和监控。

AI/GPU：计划部署 256–512 GPU，包括 NVIDIA H100/H200/B200。业务包括 LLM Training、Fine-tuning、RAG、Model Repository、Dataset、Checkpoint、AI Inference。NAS 可被 GPU 服务器直接访问，支持 NVIDIA DGX、Base Command、Kubernetes GPU Operator、Slurm、PyTorch、TensorFlow、Hugging Face、Ray；优选 GPUDirect Storage、RDMA、100/200/400GbE、RoCE。重点验证 large sequential read、random read、small file metadata、checkpoint burst write，并通过 per-workload QoS 防止 AI Job 影响普通企业 NAS 用户。

数据分析与统一数据访问：平台包括 Spark、Trino、Presto、Kafka、Flink、Databricks。希望分析平台直接读取 NAS 数据，避免复制。最好 NFS、SMB、S3 三种协议访问同一份 Dataset：AI/GPU 使用 NFS，Windows 用户使用 SMB，分析平台使用 S3。如果无法严格同一 Namespace，需要透明的数据访问或同步机制。AD、LDAP、Kerberos、ACL、Snapshot、Backup、Ransomware Protection、Replication、Cloud Tiering 必须仍然成立。

混合云：已有 AWS、Azure 和少量 GCP。支持 Amazon S3、S3 Glacier、AWS DataSync、AWS Backup、Direct Connect，以及 Azure Blob Storage、Azure Archive、Azure ExpressRoute。热数据保留本地 NAS，冷数据分层至 S3/Azure Blob，但用户访问路径尽量保持不变，例如 /projects/projectA。

备份生态：不能只使用存储厂商自己的备份软件。必须兼容 Veeam、Commvault、Veritas NetBackup、Rubrik、Cohesity、Dell Networker、IBM Storage Protect。优选 NDMP、NFS、SMB、S3、Snapshot API，并允许第三方备份软件控制 Snapshot、Backup、Restore、Clone。

快照与恢复：生产数据约 2 PB，Snapshot interval 5–15 分钟、retention 30–90 天，每天数十个 snapshot 不明显影响性能。支持 Snapshot、Writable Clone、Read-only Snapshot、Instant Restore、File-level Restore、Directory Restore、Full filesystem rollback。每文件系统优选 1000+，甚至 10000+ snapshot。

网络安全与勒索防护：Snapshot 创建后管理员也不能直接修改；删除关键 Snapshot 需要 Admin A + Admin B 双人授权。检测大量文件突然修改、扩展名异常变化、异常删除、异常加密、SMB 异常行为；发现异常后可 Alert + Snapshot + Block User/Client。优选对接 Splunk、Microsoft Sentinel、CrowdStrike、Palo Alto、ServiceNow。

网络与互操作：网络包含 10/25/100/200/400GbE。支持 LACP、VLAN、Jumbo Frame、ECMP、L3 Routing、RoCE、RDMA，并与 Cisco、Arista、Juniper、NVIDIA Spectrum 交换机互通；不得要求专有网络。

数据库与应用一致性：支持 Oracle、PostgreSQL、MySQL、SQL Server、SAP HANA backup，重点包括 Oracle RMAN、Oracle Direct NFS、PostgreSQL Backup、SQL Server Backup、SAP HANA Backup。提供数据库一致性 Snapshot API 或集成机制。

自动化：支持 REST API、Terraform、Ansible、Python SDK、CLI、Kubernetes CSI。Terraform 可创建 Filesystem、Share、Quota、Snapshot Policy、Replication、QoS；主要管理操作不能只能通过 GUI 完成。

可观测性：支持 Prometheus、Grafana、SNMP、Syslog、REST API，优选 OpenTelemetry；监控 IOPS、Bandwidth、Latency、CPU、Cache Hit、Network、Filesystem Capacity、Client IO、Protocol、Top Users、Top Files；对接 Splunk、ServiceNow、Elastic、Dynatrace。

高可用、灾备与扩展：任何 Controller、NIC、SSD、Switch、Power、Fan 单点故障不得中断业务；NAS OS 支持 Non-disruptive Upgrade。DC1 到 DC2 异步复制要求 RPO <= 15 min、RTO <= 30 min；核心业务希望 Active-Active NAS，或至少 Automatic Failover + Global Namespace。

一期 Usable Capacity 3 PB，三年 8–10 PB。扩容必须实现 Add Node -> Automatic Rebalance -> Capacity Increase -> Performance Increase，不能出现容量扩大三倍而仍受原两个 NAS Controller 限制、性能基本不变的情况；优先真正 Scale-out NAS。

请把以上内容转成可追溯的需求编号，先检查硬性门槛，再对 Huawei 与 NetApp 的适用产品和架构进行逐项竞争分析。每项事实必须注明来源、版本、配置和适用条件；严格区分 Not Compliant 与 Not Documented，不比较测试条件不同的性能数字。输出正式 DOCX，包含执行摘要、方法与来源、合规矩阵、架构与工作负载分析、风险与证据缺口、PoC 验证计划、平衡建议及来源清单。`

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
    title: "企业存储问题",
    purpose: "验证系统能否分析企业存储架构，并调用竞争分析能力比较主流全闪存产品。",
    status: "ready",
    steps: [
      {
        id: "5-competitive-analysis",
        scenarioId: "scenario-5",
        title: "NetApp AFF 与 Huawei OceanStor Dorado 对比",
        kind: "chat",
        purpose: "验证新建的竞争分析 Agent 能否按工作负载相关维度进行有来源、有边界的产品比较。",
        estimatedTime: "约 2–3 分钟",
        prompt: "请对比netapp aff 和 huawei oceanstor dorado",
        expected: ["路由至 Competitive-Analysis-Agent", "比较 NetApp AFF 与 Huawei OceanStor Dorado", "标注来源和适用条件", "区分“明确不支持”与“未找到文档”", "不直接比较测试条件不一致的性能或容量数字", "给出适用场景、取舍和可能改变结论的待验证项"],
      },
      {
        id: "5-unified-nas-docx",
        scenarioId: "scenario-5",
        title: "企业级统一 NAS 平台竞争分析 DOCX",
        kind: "chat",
        purpose: "基于完整客户需求，评估 Huawei 与 NetApp 的统一 NAS 方案并生成正式竞争分析文档。",
        estimatedTime: "约 5–10 分钟",
        prompt: unifiedNasPrompt,
        expected: ["路由至 Competitive-Analysis-Agent", "保留项目名称并将全部硬性要求转为可追溯编号", "覆盖统一多协议 NAS、Windows/Linux、VMware、Kubernetes、AI/HPC、分析、云、备份、安全、自动化、HA/DR 与扩展", "逐项比较 Huawei 与 NetApp，并标注来源、版本、配置和适用条件", "区分 Not Compliant 与 Not Documented", "给出风险、证据缺口和 PoC 计划", "返回真实可访问的 DOCX artifact；如运行时不支持则明确报告未生成，不虚构链接"],
      },
    ],
  },
  {
    id: "scenario-6",
    label: "场景 6",
    title: "建筑图纸问答",
    purpose: "验证 architecture-qa 对建筑标高、窗型缩写和空间连接关系的理解。",
    status: "ready",
    steps: [
      {
        id: "6-height-baseline",
        scenarioId: "scenario-6",
        title: "+36 标高基准",
        kind: "chat",
        purpose: "检查系统能否解释建筑平面图中的常见高度标注基准。",
        estimatedTime: "约 1 分钟",
        prompt: "The floor plan shows \"+36\" next to the vanity in the Master Bath. In architectural drawings, what does a \"+36\" height annotation typically reference as its baseline?\n\n- A. Above Finished Floor (AFF)\n- B. Above Sea Level\n- C. Above the Foundation\n- D. Above the Ceiling",
        expected: ["选择 A. Above Finished Floor (AFF)", "说明 +36 通常表示高于完成地面 36 英寸", "不把标高解释为海拔、基础或吊顶基准"],
      },
      {
        id: "6-fixed-glass",
        scenarioId: "scenario-6",
        title: "F.G. 窗型缩写",
        kind: "chat",
        purpose: "检查系统能否识别建筑窗标注中的常用玻璃类型缩写。",
        estimatedTime: "约 1 分钟",
        prompt: "The floor plan shows a window notation \"(3) 3'6\" × 3'6\" F.G.\" What type of glazing does \"F.G.\" indicate for these windows?\n\n- A. Frosted Glass\n- B. Fixed Glass\n- C. Framed Glass\n- D. Cannot be determined — F.G. meaning depends on the legend",
        expected: ["选择 B. Fixed Glass", "说明该标注表示三樘 3'6\" × 3'6\" 的固定玻璃窗", "不误解为 Frosted Glass 或 Framed Glass"],
      },
      {
        id: "6-foyer-connection",
        scenarioId: "scenario-6",
        title: "FOYER 到 MASTER BEDROOM",
        kind: "chat",
        purpose: "检查系统能否读取平面图中的房间邻接和通行关系。",
        estimatedTime: "约 1 分钟",
        prompt: "On the floor plan, what space connects the FOYER to the MASTER BEDROOM?\n\n- A. GALLERY\n- B. STUDY\n- C. HALL\n- D. They connect directly with no intermediate space",
        expected: ["选择 A. GALLERY", "依据平面图说明 FOYER 经 GALLERY 连接 MASTER BEDROOM", "不将 STUDY 或 HALL 误判为中间空间"],
      },
    ],
  },
  {
    id: "scenario-7",
    label: "场景 7",
    title: "电路板图理解",
    purpose: "从 2 号电路图抽取元件并识别尺寸最大的芯片。",
    status: "ready",
    steps: [
      {
        id: "7-chip",
        scenarioId: "scenario-7",
        title: "识别最大芯片",
        kind: "chat",
        purpose: "基于已入库板图/网表回答，而不是依赖通用电子知识。",
        estimatedTime: "约 1 分钟",
        prompt: "电路图2号里面的最大芯片是什么？",
        expected: ["识别电路图 2", "给出元件标号和尺寸/边界框证据", "答案来自已抽取板级数据"],
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
