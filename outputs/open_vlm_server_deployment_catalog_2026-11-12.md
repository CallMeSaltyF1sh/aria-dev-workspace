# 视觉语言模型服务器部署与候选清单（穿衣动作阶段识别）

更新日期：2026-11-14（候选模型按综合测试优先级重排）。项目场景：Project Aria 第一人称视频中，识别参与者给人台穿衬衫、夹克的动作阶段；比较可视与遮挡视线条件，并与人工标注对照。

## 先说结论

**可以把模型部署在实验室 GPU 服务器上，由实验室电脑通过网络调用。** 常见结构是：Aria 原始录制数据保存在受控存储中 → 按时间戳提取短片段或固定采样帧 → GPU 服务器运行 VLM 推理服务 → 客户端收到结构化阶段预测 → 与人工标注比较。服务器承受主要计算负担，电脑负责数据处理、请求和结果分析。这样通常不产生按次调用云模型的费用，但仍有服务器使用、存储和维护成本。

“开源视觉模型”没有固定且可穷尽的总名单，模型、微调版和量化版持续增加。本表**按可获取权重、能接受图像/视频并能生成文本标签的代表性模型家族**整理。表中“开源权重”不等于 OSI 意义上的开源：Gemma、Llama、DeepSeek 等须按各自许可审核。模型的通用视觉榜单成绩不是本项目的穿衣阶段准确率。

## 一、服务器部署与调用

### 1. 确认实验室条件

请管理员/同学确认：GPU 型号和每卡显存、GPU 数量、CUDA/驱动、服务器系统、可用磁盘、是否通过 SSH 或 Slurm 登录、服务器能否访问 Hugging Face、参与者视频是否允许存放在该服务器。先在分配到的 **GPU 计算节点**运行：

```bash
nvidia-smi
python3 --version
df -h
```

如果是 Slurm 集群，先申请交互 GPU 任务或提交作业，再在计算节点启动服务；不要在登录节点长期跑模型。部署工作最好使用服务器上的独立 Python 环境，不要把本机 Project Aria 的 macOS 虚拟环境复制到 Linux/CUDA 服务器。

### 2. 最容易复现的首个服务

建议先用 [Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) 建立基线：官方卡片支持图像/视频输入，[vLLM 官方配方](https://docs.vllm.ai/projects/recipes/en/stable/Qwen/Qwen2.5-VL.html)提供部署方式。以下以 **12 张抽帧图像**而非直接传整个 MP4 为例，便于跨模型固定完全相同的输入。`--max-model-len 8192` 是本实验的服务配置，**不是**模型标称上限；可根据显存调整。

```bash
python3 -m venv ~/venvs/dressing-vlm
source ~/venvs/dressing-vlm/bin/activate
python -m pip install -U pip vllm
vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 8192 \
  --limit-mm-per-prompt '{"image":12,"video":0}'
```

安装命令只是起点：GPU/CUDA 与 vLLM 版本需按服务器环境匹配，下载模型须有网络和磁盘空间；首次加载可能较慢。若显存不足，先减少帧数/图像尺寸和并发，再评估官方或受信量化权重。vLLM 的图像数量限制见[官方服务参数](https://docs.vllm.ai/en/stable/cli/serve/)。新架构如 Qwen3.5/3.6 可能要求特定新版或 nightly vLLM，应按各自模型卡部署，不能假设换一个模型 ID 就能运行。

服务器只监听 `127.0.0.1`。在实验室电脑另开终端建立 SSH 隧道：

```bash
ssh -N -L 8000:127.0.0.1:8000 USER@GPU_SERVER
```

若使用 Slurm 计算节点，应先按实验室的跳板/端口转发规则把隧道连接到实际计算节点。隧道建立后，本机访问 `http://127.0.0.1:8000/v1`；不要为方便而把含参与者画面的服务端口直接暴露到公网。

检查服务：

```bash
curl http://127.0.0.1:8000/v1/models
```

### 3. 从电脑发送帧并收回预测

下面的最小客户端只依赖 Python 标准库。先从 VRS/视频按固定时间戳导出 JPEG；文件名按时间排序，例如 `0000.jpg`、`0001.jpg`。这段代码演示接口，不会自动读取 VRS：

```python
import base64
import json
from pathlib import Path
from urllib.request import Request, urlopen

frames = sorted(Path("frames/clip_001").glob("*.jpg"))[:12]
assert frames, "No JPEG frames found"

content = [{"type": "text", "text": (
    "These are chronologically ordered frames from one egocentric dressing clip. "
    "Identify the dominant phase using only visible evidence. "
    "Allowed labels: approach_garment, orient_garment, insert_arm, pull_or_adjust, "
    "fasten_or_close, completion, uncertain. "
    "Return JSON with label, short_evidence, uncertainty_reason. "
    "Do not infer tactile force from the images."
)}]
for frame in frames:
    data = base64.b64encode(frame.read_bytes()).decode("ascii")
    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})

payload = {
    "model": "Qwen/Qwen2.5-VL-7B-Instruct",
    "messages": [{"role": "user", "content": content}],
    "temperature": 0,
    "max_tokens": 220,
}
request = Request(
    "http://127.0.0.1:8000/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=180) as response:
    result = json.load(response)
print(result["choices"][0]["message"]["content"])
```

这是[vLLM 的兼容 Chat Completions 多模态接口](https://docs.vllm.ai/en/stable/features/multimodal_inputs/)。正式实验应记录 `model_id` 与权重修订号、运行框架版本、精度/量化、抽帧时间戳、帧率与帧数、图像尺寸、提示词、解码参数、响应时间和原始输出。也要验证每次输出是否能解析为指定 JSON；失败应单独计数，不能悄悄改写标签。

## 二、候选模型清单

说明：参数量通常采用**型号标称规模**，不保证包含视觉编码器的精确总参数；MoE 同时列“总参数/每次激活参数”。`K`=千 token，`M`=百万 token。上下文长度是模型/卡片标称的 token 限制，**不等于能处理同样数量的视频帧**。高分辨率图像可占大量视觉 token；实际可用片长取决于采样、缩放、服务配置、显存和推理引擎。`待核实`表示未在该官方模型卡找到可直接确认的统一数字，须在选定 checkpoint 的 `config.json`、processor 和实机加载后验证。

“项目用途”是**基于模型输入能力的测试建议，不是已测穿衣识别准确率**。以下按本项目的**综合测试优先级**排序：短片段阶段识别的任务贴合度、可复现的部署路径、未知 GPU 配置下的资源成本，以及提供不同错误类型对照的研究价值。排序是定性判断，没有伪造综合分数；若实验室有 80GB 或多卡 GPU，大模型可提前测试。图像模型可用多帧输入做对照，但要记录不同输入路径。

| 综合顺序 | 候选与官方权重 | 规模 | 图像/视频输入 | 标称上下文 | 视觉识别特点与本项目用途 | 推荐理由 | 许可/备注 |
|---:|---|---:|---|---:|---|---|---|
| 1 |  [Qwen3-VL-Instruct](https://huggingface.co/collections/Qwen/qwen3-vl)：[4B](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)、[8B](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)、[32B](https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct) | 4/8/32B；另有 MoE 30B-A3B、235B-A22B | 图像、视频 | 8B 卡：原生 256K；可扩展至 1M | **核心基线**：视频、空间和动作理解；4B/8B 适合先跑小样本 | 原生视频，4B/8B 覆盖常见实验室显存；有 vLLM 专门配方，适合作主基线。 | Apache-2.0（示例卡）；扩展长度不是默认可用帧数  |
| 2 |  [Qwen2.5-VL-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) | 3/7/32/72B 型号 | 图像、视频 | 7B 配置原生 32K；扩展需额外设置 | **成熟对照基线**：动作/物体、时序、定位；vLLM 配方成熟 | 视频输入与部署配方成熟；便于先跑通完整评测管线并作旧代对照。 | Apache-2.0（7B 卡）；实测阶段性能未知  |
| 3 |  [Qwen3.5 系列](https://huggingface.co/collections/Qwen/qwen35)：[0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B)、[2B](https://huggingface.co/Qwen/Qwen3.5-2B)、[4B](https://huggingface.co/Qwen/Qwen3.5-4B)、[9B](https://huggingface.co/Qwen/Qwen3.5-9B)、[27B](https://huggingface.co/Qwen/Qwen3.5-27B)、[35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | 0.8/2/4/9/27B；MoE 35B 总/3B 激活 | 原生图像、视频 | 4B 官方卡：原生 262K，扩展约 1M；其他逐 checkpoint 核对 | **首选新一代尺寸梯度**：4B→9B→27B，可检验规模对遮挡、手衣交互的影响 | 原生图像/视频且有 4B/9B 尺寸梯度；研究价值高，但新版推理框架增加部署工作。 | Apache-2.0；4B 卡片提示新版 vLLM/SGLang  |
| 4 |  [Molmo2-8B](https://huggingface.co/allenai/Molmo2-8B) | 8B 型号 | 图像、多图、视频 | 待核实 | **定位/跟踪对照**：可研究手、衣袖、领口的指向与跟踪输出 | 提供视频指向与跟踪能力，适合分析手、袖口和衣服的可见交互；部署需自定义代码。 | Apache-2.0；示例使用 `trust_remote_code`  |
| 5 |  [InternVL3.5](https://huggingface.co/OpenGVLab/InternVL3_5-8B) | 约 1.1/2.3/4.7/8.5/15.1/38.4B 总；另有 MoE | 图像、多图、视频 | 官方卡 SFT 阶段 32K；部署上限按 checkpoint 核对 | 高分辨率与多帧视觉对照；可看衣袖、边缘等细节 | 多图与视频、高分辨率细节能力适合遮挡/衣袖边界；作为不同架构对照。 | Apache-2.0；部分实现需 `trust_remote_code`  |
| 6 |  [VideoLLaMA3](https://huggingface.co/DAMO-NLP-SG/VideoLLaMA3-7B) | 2/7B | 图像、视频 | 7B 配置 32K | 视频专门模型；测试动作先后顺序、时间线 | 视频专用、7B 可及；有助检验阶段先后顺序，部署代码相对不统一。 | Apache-2.0（7B 卡）；自定义代码  |
| 7 |  [LLaVA-Video](https://huggingface.co/lmms-lab/LLaVA-Video-7B-Qwen2) | 7/72B | 图像、多图、视频 | 32K；7B 卡写明至多 64 帧 | **视频专门对照**：帧数限制明确，适合短片段 | 视频专项且 64 帧上限明确，适合短片段；作为较早视频架构对照。 | 按模型卡核对；7B 优先  |
| 8 |  [SmolVLM2](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct) | 256M/500M/2.2B | 图像、视频 | 待核实；实际运行配置必须核对 | **低成本下限基线**：快速检查标签/流程是否可学可测；小模型可能漏掉细动作 | 2.2B 及更小尺寸易建立低成本下限；细微动作判别能力需实测。 | Apache-2.0（2.2B 卡）；家族提供视频评测  |
| 9 |  [MiniCPM-V 4.5](https://huggingface.co/openbmb/MiniCPM-V-4_5) | 8.7B | 图像、视频 | 待核实 | 轻量视频候选；官方展示 Video-MME/速度数据，适合与 Qwen 8B 比 | 8.7B 视频模型，可补充效率比较；上下文和服务实现需先核实。 | 以模型卡许可为准；自定义推理代码需核对  |
| 10 |  [GLM-4.1V-9B-Thinking](https://huggingface.co/zai-org/GLM-4.1V-9B-Thinking) | 9B 型号 | 图像、视频 | 64K | 视觉推理对照；检验复杂接触/遮挡解释是否改善阶段判断 | 可检验视觉推理是否改善遮挡解释；思考输出可能增加延迟和解析难度。 | MIT；推理输出可能更长、更慢  |
| 11 |  [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 27B 类 | 图像、视频 | 原生 262K；扩展至 1M 需额外配置 | 新版长上下文视频候选；大 GPU 资源时测试细微阶段 | 最新大模型可作资源充足时的高容量对照；单卡显存与框架门槛较高。 | Apache-2.0；先核对推理框架支持  |
| 12 |  [Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B) / [35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | 27B；35B 总/3B 激活 | 图像、视频 | 27B 原生 262K；35B 单独核对 | 多帧时序与复杂推理候选；MoE 的显存按总权重估算 | 大模型视频对照；与 Qwen3.5/3.8 高度同族，增量研究价值较低。 | Apache-2.0；大模型/多卡优先  |
| 13 |  [LLaVA-OneVision](https://huggingface.co/lmms-lab/llava-onevision-qwen2-7b-ov) | 0.5/7/72B | 图像、多图、视频 | 7B 约 32K，按 checkpoint 核对 | 与 LLaVA-Video 比较：通用多模态与视频专项训练 | 通用图像/视频基线，可与 LLaVA-Video 成对比较；优先级低于视频专项版。 | 按模型卡核对  |
| 14 |  [Gemma 3 IT](https://huggingface.co/google/gemma-3-4b-it) | 4/12/27B（1B 为纯文本，不列入） | 图像、多图；非原生视频 | 128K | 多帧图像基线；比较“仅看离散帧”与原生视频模型 | 多帧图像基线、128K 上下文；不原生处理视频时序，需注意许可。 | Gemma 条款；非 OSI 开源许可  |
| 15 |  [Pixtral-12B-2409](https://huggingface.co/mistralai/Pixtral-12B-2409) | 12B 解码器 + 0.4B 视觉编码器 | 图像、多图；非原生视频 | 128K | 可变图像尺寸；比较手、衣服局部细节辨认 | 多图与高分辨率视觉对照；12B+视觉编码器成本较高且非原生视频。 | Apache-2.0  |
| 16 |  [Phi-4-multimodal-instruct](https://huggingface.co/microsoft/Phi-4-multimodal-instruct) | 5.6B 型号 | 图像、音频；非原生视频 | 128K | 图像加口述的探索性对照；**正式盲测不应给测试片段的标注性口述答案** | 图像+音频适合另设口述实验；核心视觉盲测不应输入答案性口述。 | MIT；音频/视觉适配与部署配置较复杂  |
| 17 |  [DeepSeek-VL2](https://huggingface.co/deepseek-ai/deepseek-vl2) | Tiny/Small/Full：1/2.8/4.5B 激活；Full 约 27B 总 | 图像、多图；非原生视频 | 待核实 | 多图视觉推理对照；MoE 显存按总权重准备 | 多图 MoE 对照；自定义许可、总权重显存与非原生视频降低首轮价值。 | DeepSeek 自定义许可，逐条核对  |
| 18 |  [PaliGemma 2 Mix](https://huggingface.co/google/paligemma2-3b-mix-224) | 3/10/28B | 主要单图；非原生视频 | 不宜套用通用长上下文数字；逐 checkpoint 核对 | 单帧物体/服装定位对照；不适合作为主要阶段时序模型 | 偏单帧视觉任务，可做服装部件识别；不适合直接判断连续阶段。 | Gemma 条款；用 **mix** 而非未指令微调的 `pt` 作即用测试  |
| 19 |  [Llama 4 Scout / Maverick](https://ai.meta.com/resources/models-and-libraries/llama-downloads/) | Scout 109B 总/17B 激活；Maverick 400B 总/17B 激活 | 图像、多图；非原生视频 | Scout 10M；Maverick 按卡核对 | 大规模多图参考上界；通常超出小实验室单卡预算 | 参数总量和访问/许可门槛高，且本研究所需短视频阶段评测收益不确定。 | Llama 4 Community License；可能须申请访问  |

**表格阅读提示：**“图像识别能力”没有一个通用强弱值。OCR、图像问答、视频时间顺序、目标定位和本实验的手与衣服阶段判别是不同任务。表中的“擅长/用途”只根据官方公布的输入和功能定位；项目的真实排序必须通过同一批人工标注片段测得。对部分较新的权重，推理框架支持与许可可能更新，正式试验前应锁定模型修订号和软件版本。

## 三、本项目建议的测试顺序

1. **先建立数据与基线**：优先 Qwen3-VL-4B/8B，再用 Qwen2.5-VL-7B 作成熟对照，选 20–30 个 10–20 秒片段，覆盖衬衫/夹克、可视/遮挡、各阶段；固定 1–2 FPS、最大帧数、分辨率、提示词、标签集合和输出格式。
2. **比较不同家族**：在完全相同的帧输入下按表中顺序扩展到 Qwen3.5-4B/9B、Molmo2-8B、InternVL3.5-8B、VideoLLaMA3-7B、LLaVA-Video-7B、SmolVLM2-2.2B。若原生视频接口可用，再单独做“原生视频 vs 相同抽帧”的条件实验；不能把不同采帧策略混成模型能力排名。
3. **测边界而非只报总体准确率**：分别统计阶段准确率、macro-F1、阶段边界时间误差、`uncertain` 比例、无效 JSON 比例、耗时；按遮挡视线、衣服遮住手、袖口可见度、相邻阶段、拉扯/反复调整、第一人称镜头运动分类错误。
4. **保持评测独立**：人工标签和参与者简短口述用于建立/复核 ground truth；在零样本评测时，不能把同一测试片段的人类标签或能直接透露答案的口述交给模型。若要做 few-shot/微调，应明确另设参与者级隔离的训练集与测试集。

### 显存粗估和决策

BF16/FP16 权重粗略约 `2 × 参数量(B)` GB；4-bit 权重主体粗略约 `0.5 × 参数量(B)` GB，**还要额外计入**视觉编码器、量化元数据、KV cache、视频帧、并发和框架开销。例如 7–9B 的 BF16 权重本身约 14–18 GB，实际服务常需明显更多显存；MoE 的权重存储看**总参数**，不能只用激活参数估算。16/24/48/80 GB 显卡分别可优先试小模型/量化 7B、7–9B、较大 12–27B、较大或多卡方案；这只是起点，必须以实机加载与目标帧数的峰值显存验证。

### 数据与记录

保留 Aria 原始 VRS 和设备时间戳；把推理输入帧、人工标签、模型输出分开存。OptiTrack 轨迹可用于事后解释手/身体运动与阶段边界，但不能当成视觉模型直接可见的信息，也不能当作触觉力。含参与者画面的数据优先经实验室批准的受控服务器处理，并遵循项目的同意与访问要求。

## 官方资料入口

- [vLLM 多模态输入](https://docs.vllm.ai/en/stable/features/multimodal_inputs/)；[服务参数](https://docs.vllm.ai/en/stable/cli/serve/)；[Qwen2.5-VL 配方](https://docs.vllm.ai/projects/recipes/en/stable/Qwen/Qwen2.5-VL.html)。
- [Qwen3.5-4B 模型卡（上下文与 vLLM/SGLang 部署命令）](https://huggingface.co/Qwen/Qwen3.5-4B)；[Qwen3-VL 系列](https://huggingface.co/collections/Qwen/qwen3-vl)。
- [SmolVLM2 模型卡](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)；[Molmo2 模型卡](https://huggingface.co/allenai/Molmo2-8B)；[LLaVA-Video 模型卡](https://huggingface.co/lmms-lab/LLaVA-Video-7B-Qwen2)。
- [Gemma 3 视觉尺寸与上下文](https://huggingface.co/blog/gemma3)；[Pixtral-12B 模型卡](https://huggingface.co/mistralai/Pixtral-12B-2409)；[Meta Llama 4 官方规格](https://ai.meta.com/resources/models-and-libraries/llama-downloads/)。
