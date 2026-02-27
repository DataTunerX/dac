模块名称： 应用启动与配置

模块业务描述： 负责控制器管理器的程序入口、命令行配置解析、全局配置加载以及核心管理器启动流程。

main.go
文件摘要: 本文件是DataTunerX控制器管理器的主程序入口，负责初始化并启动Kubernetes控制器管理器，以管理自定义资源（CR）的生命周期和协调逻辑。

cmd/controller-manager/app/options/options.go
文件摘要: 本文件定义了控制器管理器的命令行配置选项，用于控制领导选举的租约参数、监控和健康检查端点地址以及证书轮换器的启用状态。

cmd/controller-manager/app/controller_manager.go
文件摘要: 本文件是控制器管理器的主入口，负责初始化并启动Kubernetes Operator的控制器管理器。它配置了管理器的核心参数，注册了自定义资源（CRD）的Scheme，设置了证书轮换，并注册了多个控制器和Webhook来处理微调作业、微调实验、LLM、超参数和数据集等业务资源。

=====

模块名称： 微调作业控制器模块

模块业务描述： 负责管理大语言模型微调作业（FinetuneJob）的完整生命周期，协调初始化、训练、构建、部署和评分等阶段的状态流转。

internal/controller/finetune/finetunejob_controller.go
文件摘要: 本文件是FinetuneJob的Kubernetes控制器，负责协调和管理大语言模型（LLM）微调作业的完整生命周期。它通过监听相关资源（Finetune、Job、RayService、Scoring）的状态变化，驱动微调作业按顺序经历初始化、微调、构建镜像、服务部署和评分等阶段，并最终完成或失败。

pkg/util/generate/generate.go
文件摘要: 本文件是Kubernetes资源生成器，负责根据大模型微调作业（FinetuneJob）的配置，生成对应的Kubernetes资源对象，包括微调任务（Finetune）、镜像构建任务（Job）、Ray服务（RayService）和评分任务（Scoring）。

=====
模块名称： 微调任务与实验控制器模块

模块业务描述： 负责管理微调任务（Finetune）和微调实验（FinetuneExperiment）的生命周期，包括任务创建、状态协调和实验版本管理。

internal/controller/finetune/finetune_controller.go
文件摘要: 本文件是微调（Finetune）功能的Kubernetes控制器，负责协调和管理大语言模型（LLM）的微调任务。它通过监听Finetune自定义资源的状态变化，自动创建和管理RayJob分布式训练任务，并在任务完成后生成LLMCheckpoint检查点资源。

internal/controller/finetune/finetuneexperiment_controller.go
文件摘要: 本文件是Kubernetes Operator控制器，负责管理微调实验（FinetuneExperiment）的生命周期。它监听FinetuneExperiment资源的变化，根据实验规格创建和管理多个微调任务（FinetuneJob），并聚合所有子任务的状态来更新实验的整体状态，包括确定最佳版本。


=====

模块名称： 微调训练执行模块

模块业务描述： 负责大语言模型微调训练的核心流程，包括参数解析、模板处理、训练器定义、分布式训练执行以及指标监控。

cmd/tuning/train.py
文件摘要: 本文件是大型语言模型（LLM）微调训练任务的主程序，负责加载数据集、预处理数据、配置模型参数、启动分布式训练流程，并保存训练结果。它实现了基于Ray框架的分布式训练，支持LoRA等参数高效微调方法。

cmd/tuning/parser.py
文件摘要: 本文件负责定义大语言模型（LLM）微调任务的核心配置参数，包括模型参数、微调技术参数和数据参数，并提供一个统一的参数解析入口函数。它是微调流程的配置管理中心。

cmd/tuning/template.py
文件摘要: 本文件定义了一个大语言模型（LLM）对话模板系统，用于将用户查询、系统指令和历史对话转换为符合特定模型格式的token序列。它支持多种开源模型（如Llama2、Vicuna、ChatGLM等）的对话模板，并提供了单轮和多轮对话的编码功能。

cmd/tuning/trainer.py
文件摘要: 本文件定义了两种用于大语言模型（LLM）微调的训练器类：GenEvalSeq2SeqTrainer和SFTTrainer。它们扩展了Hugging Face Transformers库的基础训练器，专门处理序列到序列生成任务和指令微调（SFT）场景，核心职责包括评估时的生成参数管理、预测步骤的序列对齐与填充、以及评估指标（如困惑度）的计算。

cmd/tuning/callback.py
文件摘要: 本文件实现了一个用于大语言模型（LLM）训练过程的回调处理器，负责在训练、评估和预测的关键节点收集并记录训练指标（如损失、评估分数）和进度信息（如已用时间、剩余时间），并将这些信息输出到日志文件或外部监控系统。

cmd/tuning/prometheus/metrics.py
文件摘要: 本文件负责将机器学习训练和评估过程中的关键性能指标（如损失、学习率、困惑度等）导出到Prometheus时序数据库，用于监控和调优。它封装了Prometheus远程写入协议的数据构建和发送逻辑。

cmd/tuning/prometheus/prometheus_pb2.py
文件摘要: 本文件是Prometheus监控系统的Protocol Buffers定义文件，定义了用于写入监控指标数据和查询监控指标数据的核心数据结构。它提供了时间序列数据的写入请求、读取请求和响应的消息格式，以及查询条件、标签匹配器等组件。


=====


模块名称： 通用工具与基础设施

模块业务描述： 提供与业务逻辑无关的通用工具函数、错误处理、标签管理以及领域错误常量定义。

pkg/util/util.go
文件摘要: 本文件是一个通用工具包，提供了一系列与业务逻辑无关的辅助功能，主要用于字符串处理、数值转换和系统环境信息获取。

pkg/util/handlererr/handler.go
文件摘要: 本文件负责处理控制器运行过程中产生的错误，根据错误类型决定是否重新调度以及重新调度的延迟时间。它封装了针对特定业务错误（如重新校准错误）的差异化处理逻辑。

pkg/util/label/label.go
文件摘要: 本文件定义了微调（Finetune）系统中用于Kubernetes资源标签（Label）的常量键值对和工具函数，用于标识和管理微调作业、实验等组件的实例和归属关系。

pkg/domain/valueobject/err.go
文件摘要: 本文件定义了领域值对象包中使用的业务错误常量，用于表示特定业务场景下的错误语义。

pkg/events/events.go
文件摘要: 本文件定义了事件相关的常量，用于标识在检查依赖资源过程中成功或失败的业务事件原因。