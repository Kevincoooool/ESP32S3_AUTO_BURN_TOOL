# 数字人系统架构设计文档

> RK3588 + Unreal Engine + Pipecat 云端 Pipeline
> 实时日语语音对话 + 口唇同步 + 表情驱动 + 动作驱动

---

## 1. 概述

### 1.1 目标

构建一个实时数字人系统，具备以下能力：

- 自由日语语音对话
- 基于端侧音频驱动的实时口唇同步
- 基于状态机的情感驱动面部表情
- 基于意图的动作驱动与过渡规划
- 场景切换与角色换装
- 跨会话记忆与向量检索
- 云端 LLM 控制端侧设备（摄像头拍摄、场景/服装指令）

### 1.2 设计原则

- **LLM 模块**：语义输入 → 结构化事件输出。不包含任何渲染逻辑。
- **Emotion 模块**：事件 → 驱动指令。不包含语义理解。
- **端侧（UE）**：纯执行器。接收指令、渲染，不做决策。
- **Frame = Event**：Pipecat 的 Frame 流水线即事件总线，无需外部 pub/sub。
- **pre/final 分级**：预测性事件实现提前响应；最终事件锁定状态。

### 1.3 技术栈

| 层级 | 技术 |
|------|------|
| 端侧硬件 | RK3588 (Android) |
| 端侧渲染 | Unreal Engine 5（自定义数字人模型）|
| 云端框架 | Pipecat (Python, 基于 Frame 的流水线) |
| 传输协议 | WebSocket (公网) |
| STT | Azure Speech (日语流式识别) |
| LLM | 定制模块（Gemini 3.0 Flash 多模态 + Function Calling）|
| TTS | Fish Audio (日语流式 WebSocket) |
| 端侧口唇同步 | 音频驱动口型分析（RK3588 本地处理）|
| 数据库 | PostgreSQL + pgvector |
| 缓存 | Redis |

---

## 2. 系统架构

### 2.1 部署拓扑

```
┌─── RK3588 端侧设备 (Android + UE5) ────┐
│                                            │
│  麦克风 / 扬声器 / 摄像头 / HDMI 显示屏   │
│           ↕                                │
│  UE 应用程序                               │
│  ├─ WebSocket 客户端                       │
│  ├─ CommandDispatcher (指令分发器)         │
│  ├─ Audio Playback (音频播放)              │
│  ├─ Morph Target Controller (变形目标控制) │
│  ├─ Animation Blueprint (动画蓝图)         │
│  └─ UI Layer (UI 层)                       │
│                                            │
└──────────────┬─────────────────────────────┘
               │ WebSocket (wss://)
               │ 公网
               │
┌──────────────┴─────────────────────────────┐
│           云端服务器                         │
│                                             │
│  ┌─ Pipecat Pipeline (9 环节) ───────────┐ │
│  │ Transport.Input → STT → Aggregator    │ │
│  │ → MemoryRetriever → CustomLLM → TTS   │ │
│  │ → EmotionModule → OutputProcessor     │ │
│  │ → Transport.Output → Aggregator       │ │
│  │                                        │ │
│  │ Observer: MemoryWriterObserver         │ │
│  └───────────────────────────────────────┘ │
│                                             │
│  ┌─ 存储 ─────────────────────────────┐   │
│  │ PostgreSQL + pgvector │ Redis       │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─ 云端 AI 服务（内网调用）──────────┐   │
│  │ Azure STT │ Fish Audio │ Gemini    │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### 2.2 数据流概览

```
         上行链路 (端侧 → 云端)              下行链路 (云端 → 端侧)
       ┌─────────────────────┐              ┌──────────────────────┐
       │ audio (二进制 PCM)  │              │ audio (二进制 PCM)   │
       │ image (JSON+base64) │              │ SET_EMOTION (JSON)   │
       │ control (JSON)      │              │ PLAY_MOTION (JSON)   │
       └─────────────────────┘              │ SET_MODE    (JSON)   │
                                            │ SET_GAZE    (JSON)   │
                                            │ device_cmd  (JSON)   │
                                            │ scene/costume (JSON) │
                                            └──────────────────────┘
                                            注: 口唇同步由端侧从音频
                                            PCM 实时分析，无需下行
```

---

## 3. WebSocket 协议

每个设备使用一条双向 WebSocket 连接。二进制帧传输音频，文本帧传输 JSON 消息。

### 3.1 上行消息 (端侧 → 云端)

#### 音频（二进制帧）

来自麦克风的原始 PCM 音频流。

```
格式: PCM 16-bit 有符号小端序, 单声道
采样率: 16000 Hz
分块大小: 20ms (640 bytes)
```

#### 图像（文本帧，按需触发）

```json
{
    "type": "image",
    "data": "<base64 编码的 JPEG>",
    "width": 640,
    "height": 480,
    "trigger": "llm_request | user_button | sensor"
}
```

#### 控制（文本帧）

```json
{"type": "control", "action": "interrupt"}
{"type": "control", "action": "switch_scene", "scene": "office"}
{"type": "control", "action": "switch_costume", "costume": "kimono"}
{"type": "control", "action": "device_response",
 "request_id": "uuid", "status": "success", "data": {...}}
```

### 3.2 下行消息 (云端 → 端侧)

#### 音频（二进制帧）

TTS 音频用于播放。

```
格式: PCM 16-bit 有符号小端序, 单声道
采样率: 24000 Hz
```

#### 驱动指令（文本帧）

```json
{"type": "SET_EMOTION",
 "emotion": "happy", "intensity": 0.8,
 "fadeMs": 300, "mouthOverride": false, "ts": 1708901234567}

{"type": "PLAY_MOTION",
 "plan": {"kind": "CROSS_FADE", "to": "wave_01", "fadeMs": 400},
 "ts": 1708901234567}

{"type": "PLAY_MOTION",
 "plan": {"kind": "PARAM_MORPH", "params": {"speed": 1.2, "energy": 0.8}},
 "ts": 1708901234568}

{"type": "PLAY_MOTION",
 "plan": {"kind": "BRIDGE", "bridgeClip": "hand_down_bridge", "to": "bow_01"},
 "ts": 1708901234569}

{"type": "PLAY_MOTION",
 "plan": {"kind": "SAFE_ROUTE",
          "exit": "current_safe_exit", "idle": "standing_idle",
          "entry": "bow_entry", "to": "bow_01"},
 "ts": 1708901234570}

{"type": "SET_MODE", "mode": "SPEAKING", "ts": 1708901234567}

{"type": "SET_GAZE", "target": "user", "weight": 1.0, "ts": 1708901234567}
```

#### 设备指令（文本帧）

```json
{"type": "device_cmd", "action": "capture_camera",
 "request_id": "uuid", "params": {"resolution": "640x480"}}

{"type": "device_cmd", "action": "switch_scene",
 "params": {"scene": "office", "ue_level": "/Game/Levels/Office",
            "transition": "fade"}}

{"type": "device_cmd", "action": "switch_costume",
 "params": {"costume": "kimono", "ue_asset": "/Game/Characters/Costumes/Kimono",
            "transition": "fade"}}

{"type": "device_cmd", "action": "play_effect",
 "params": {"effect": "sparkle", "target": "hand_right"}}

{"type": "device_cmd", "action": "show_ui",
 "params": {"element": "subtitle", "visible": true}}
```

#### 文本显示（文本帧，可选字幕）

```json
{"type": "text", "text": "こんにちは", "role": "assistant", "final": true}
```

---

## 4. 云端 Pipeline 设计

### 4.1 Pipeline 结构

```python
pipeline = Pipeline([
    ws_transport.input(),              # UESerializer 反序列化上行数据
    stt,                               # Azure STT 日语（流式）
    context_aggregator.user(),         # 用户轮次聚合（文本 + 图像）

    memory_retriever,                  # 查询记忆 → 注入 LLM 上下文

    custom_llm,                        # LLM 模块：语义 → 结构化事件
                                       #   PromptManager 内部注入场景 prompt (从 Redis 读取)
                                       #   输出: LLMTextFrame
                                       #         EmotionEventFrame
                                       #         ActionEventFrame
                                       #         DeviceCommandFrame (function calls, 含场景/服装切换)

    tts,                               # FishAudioTTSService
                                       #   消费: LLMTextFrame
                                       #   产出: TTSAudioRawFrame
                                       #   透传: EmotionEventFrame, ActionEventFrame
                                       #   注: Fish Audio 不提供 viseme 数据，
                                       #       口唇同步由端侧音频驱动实现

    emotion_module,                    # Emotion 模块：事件 → 驱动指令
                                       #   消费: EmotionEventFrame, ActionEventFrame,
                                       #         生命周期帧
                                       #   产出: SetEmotionDriverFrame, PlayMotionDriverFrame,
                                       #         SetModeDriverFrame
                                       #   透传: TTSAudioRawFrame

    dh_output_processor,               # 所有 DriverFrame → OutputTransportMessageFrame (JSON)
                                       # DeviceCommandFrame → OutputTransportMessageFrame (JSON)

    ws_transport.output(),             # UESerializer 序列化下行数据
    context_aggregator.assistant(),    # 助手轮次聚合
])

# --- 不在 pipeline 中的组件 ---

# MemoryWriter 作为 Observer 挂载（仅观察帧流，不阻塞 pipeline）
# 见 §6.6

# 场景/服装切换在 transport 事件层处理（仅响应端侧发起的控制消息）
# LLM 发起的切换通过 function call → DeviceCommandFrame 下行
# 见 §6.7
```

### 4.2 Frame 流转图

```
ws_transport.input()
  │  InputAudioRawFrame (来自二进制帧)
  │  UserImageRawFrame (来自 JSON image, 按需)
  │  InputTransportMessageFrame (来自 JSON control)
  ↓
stt
  │  TranscriptionFrame
  │  (透传: UserImageRawFrame, InputTransportMessageFrame)
  ↓
context_aggregator.user()
  │  OpenAILLMContextFrame (文本 + 可选图像)
  ↓
memory_retriever
  │  (增强: 向 OpenAILLMContextFrame 注入检索到的记忆)
  ↓
custom_llm
  │  (PromptManager 从 Redis 读取当前 scene_id, 注入场景 prompt)
  │  LLMTextFrame (流式文本块，已剥离元数据)
  │  EmotionEventFrame (emotion, intensity, confidence, stage)
  │  ActionEventFrame (intent, gesture_hint, confidence, timing, stage)
  │  DeviceCommandFrame (capture_camera, switch_scene, play_effect 等)
  │  FunctionCallInProgressFrame / FunctionCallResultFrame
  ↓
tts (FishAudioTTSService)
  │  TTSStartedFrame
  │  TTSAudioRawFrame (音频块, 端侧同时用于音频驱动口唇同步)
  │  TTSStoppedFrame
  │  (透传: EmotionEventFrame, ActionEventFrame, DeviceCommandFrame)
  ↓
emotion_module
  │  SetEmotionDriverFrame (来自 EmotionEventFrame)
  │  PlayMotionDriverFrame (来自 ActionEventFrame)
  │  SetModeDriverFrame (来自生命周期帧)
  │  (透传: TTSAudioRawFrame, DeviceCommandFrame)
  ↓
dh_output_processor
  │  OutputTransportMessageFrame (各 DriverFrame 的 JSON)
  │  OutputTransportMessageFrame (DeviceCommandFrame 的 JSON)
  │  (透传: TTSAudioRawFrame → 由 transport 音频路径处理)
  ↓
ws_transport.output()
  │  二进制 WebSocket 帧 (音频)
  │  文本 WebSocket 帧 (JSON 指令)
  ↓
context_aggregator.assistant()
```

### 4.3 服务端入口

```python
# server.py - 云端服务应用

from fastapi import FastAPI, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.transports.websocket.server import (
    WebsocketServerTransport,
    WebsocketServerParams,
)

app = FastAPI()

async def create_pipeline(ws_transport):
    stt = AzureSTTService(api_key=..., region=..., language="ja-JP")

    custom_llm = CustomLLMProcessor(
        model="gemini-3.0-flash",       # Gemini 3.0 Flash: 流式 + Function Calling
        api_key=...,
        tools=TOOL_DEFINITIONS,
        system_prompt=BASE_SYSTEM_PROMPT,
    )

    tts = FishAudioTTSService(
        api_key=...,
        model_id="...",                 # Fish Audio 日语语音模型 ID
        params=FishAudioTTSService.InputParams(
            language=Language.JA_JP,
        ),
    )

    context_aggregator = custom_llm.create_context_aggregator()

    pipeline = Pipeline([
        ws_transport.input(),
        stt,
        context_aggregator.user(),
        MemoryRetriever(db=db, redis=redis, timeout_ms=200),
        custom_llm,
        tts,
        EmotionModule(config=load_motion_config()),
        DigitalHumanOutputProcessor(),
        ws_transport.output(),
        context_aggregator.assistant(),
    ])

    # MemoryWriter 作为 Observer（不在 pipeline 中，仅观察帧流）
    memory_observer = MemoryWriterObserver(db=db, redis=redis)

    return pipeline, memory_observer

@app.websocket("/ws/digital-human")
async def websocket_endpoint(websocket: WebSocket):
    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            serializer=UEFrameSerializer(redis=redis),
        ),
    )

    # 注册端侧场景/服装切换的事件处理器
    @transport.event_handler("on_client_connected")
    async def on_connected(transport, websocket):
        logger.info(f"Client connected: {websocket.remote_address}")

    pipeline, memory_observer = await create_pipeline(transport)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
        observers=[memory_observer],   # Observer 挂载到 task
    )

    runner = PipelineRunner()
    await runner.run(task)
```

---

## 5. Frame 类型定义

### 5.1 Frame 层次结构

```
Frame (基类)
├── SystemFrame (高优先级, 不受中断影响)
│   ├── InputAudioRawFrame          [已有]
│   ├── InputImageRawFrame          [已有]
│   ├── InputTransportMessageFrame  [已有]
│   └── InterruptionFrame           [已有]
│
├── DataFrame (按序处理, 被中断取消)
│   ├── LLMTextFrame                [已有]
│   ├── TTSAudioRawFrame            [已有]
│   ├── OutputTransportMessageFrame [已有]
│   ├── EmotionEventFrame           [新增]
│   ├── ActionEventFrame            [新增]
│   ├── DeviceCommandFrame          [新增]
│   ├── DeviceResponseFrame         [新增]
│   ├── SetEmotionDriverFrame       [新增]
│   ├── PlayMotionDriverFrame       [新增]
│   ├── SetModeDriverFrame          [新增]
│   └── SetGazeDriverFrame          [新增]
│   注: Viseme 相关 Frame 不再经过云端 pipeline，
│       口唇同步完全由端侧音频驱动处理
│
└── ControlFrame (按序处理, 控制信号)
    ├── TTSStartedFrame             [已有]
    ├── TTSStoppedFrame             [已有]
    ├── UserStartedSpeakingFrame    [已有]
    ├── UserStoppedSpeakingFrame    [已有]
    ├── BotStartedSpeakingFrame     [已有]
    └── BotStoppedSpeakingFrame     [已有]
```

**两层 Frame 架构说明：**

- **第一层（LLM → EmotionModule）**：`EmotionEventFrame`、`ActionEventFrame` — 这些是语义级事件，描述"发生了什么"
- **第二层（EmotionModule → 端侧渲染器）**：`SetEmotionDriverFrame`、`PlayMotionDriverFrame`、`SetModeDriverFrame`、`SetGazeDriverFrame` — 这些是驱动级指令，描述"怎么做"
- **端侧本地**：口唇同步由端侧直接从 TTS 音频 PCM 数据实时分析生成，不经过云端 pipeline

这种分层使 LLM 模块和渲染层完全解耦，EmotionModule 作为中间翻译层。

### 5.2 LLM 输出事件帧

```python
# src/pipecat/frames/digital_human.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pipecat.frames.frames import DataFrame


# ── 第一层: LLM → Emotion Module ──────────────────────────

@dataclass
class EmotionEventFrame(DataFrame):
    """由 CustomLLM 在流式输出中产生的情感事件。

    Parameters:
        emotion: 离散情感标签（如 "happy", "sad", "neutral"）。
        intensity: 连续强度值 0.0-1.0。
        confidence: 模型置信度 0.0-1.0。
        stage: "pre"（预测性，可撤回）或 "final"（确认，锁定状态）。
    """
    emotion: str = "neutral"
    intensity: float = 0.5
    confidence: float = 0.5
    stage: str = "pre"


@dataclass
class ActionEventFrame(DataFrame):
    """由 CustomLLM 在流式输出中产生的动作/手势事件。

    Parameters:
        intent: 语义意图类别（如 "greeting", "thinking"）。
        gesture_hint: 建议手势（如 "wave", "nod"）。
        confidence: 模型置信度 0.0-1.0。
        timing_start_offset_ms: 相对于当前语句的起始偏移。
        timing_duration_ms: 建议持续时间。
        stage: "pre"（预测性）或 "final"（确认）。
    """
    intent: str = ""
    gesture_hint: str = ""
    confidence: float = 0.5
    timing_start_offset_ms: int = 0
    timing_duration_ms: int = 2000
    stage: str = "pre"


@dataclass
class DeviceCommandFrame(DataFrame):
    """云端 LLM 通过 Function Call 发送给端侧设备的指令。

    Parameters:
        action: 指令动作标识。
        request_id: 用于请求-响应关联的唯一 ID。
        params: 指令特定参数。
    """
    action: str = ""
    request_id: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceResponseFrame(DataFrame):
    """端侧设备对 DeviceCommand 的响应。

    Parameters:
        action: 原始指令动作。
        request_id: 与原始指令匹配的关联 ID。
        status: "success" 或 "error"。
        data: 响应载荷。
    """
    action: str = ""
    request_id: str = ""
    status: str = "success"
    data: Optional[Dict[str, Any]] = None


# ── 第二层: Emotion Module → 端侧渲染器 ─────────────────

@dataclass
class SetEmotionDriverFrame(DataFrame):
    """驱动端侧渲染器的面部表情。

    Parameters:
        emotion: 目标情感。
        intensity: 目标强度 0.0-1.0。
        fade_ms: 过渡持续时间（毫秒）。
        mouth_override: 若为 false，仅应用于非嘴部 blendshape
                        （说话期间嘴部由 viseme 控制）。
    """
    emotion: str = "neutral"
    intensity: float = 0.5
    fade_ms: int = 300
    mouth_override: bool = True


@dataclass
class PlayMotionDriverFrame(DataFrame):
    """驱动端侧渲染器的身体动作/手势。

    Parameters:
        plan_kind: 过渡类型（CROSS_FADE / PARAM_MORPH / BRIDGE / SAFE_ROUTE）。
        plan_data: MotionPlan 参数，结构取决于 plan_kind。
    """
    plan_kind: str = "CROSS_FADE"
    plan_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SetModeDriverFrame(DataFrame):
    """驱动端侧渲染器的整体角色状态。

    Parameters:
        mode: 角色模式（IDLE / LISTENING / SPEAKING / THINKING）。
    """
    mode: str = "IDLE"


@dataclass
class SetGazeDriverFrame(DataFrame):
    """驱动端侧渲染器的视线方向。

    Parameters:
        target: 视线目标标识。
        weight: 混合权重 0.0-1.0。
    """
    target: str = "user"
    weight: float = 1.0
```

---

## 6. 模块详细规格

### 6.1 CustomLLM 模块

**职责**：语义输入 → 结构化事件输出。仅此而已。

**继承**：`FrameProcessor`

**消费**：`OpenAILLMContextFrame`

**产出**：`LLMTextFrame`、`EmotionEventFrame`、`ActionEventFrame`、`DeviceCommandFrame`

#### 内部架构

```
┌─── CustomLLMProcessor ──────────────────────────────────────────┐
│                                                                   │
│  OpenAILLMContextFrame                                            │
│         ↓                                                         │
│  ┌─ PromptManager ──────────────────────────────────────────┐    │
│  │  组装 system prompt:                                      │    │
│  │    base_persona + scene_prompt + memory_context + tools    │    │
│  └───────────────────────────────────────────────────────────┘    │
│         ↓                                                         │
│  ┌─ LLM API 调用 (流式) ───────────────────────────────────┐    │
│  │  model: Gemini 3.0 Flash (默认, 支持流式 Function Call) │    │
│  │  tools: TOOL_DEFINITIONS                                  │    │
│  │  stream: true                                             │    │
│  └───────────────────────────────────────────────────────────┘    │
│         ↓                                                         │
│  ┌─ StreamParser ────────────────────────────────────────────┐   │
│  │  Token 累加器扫描结构化标记：                               │   │
│  │                                                            │   │
│  │  纯文本       → 缓冲 → LLMTextFrame                       │   │
│  │  [EMO:...] 标签 → 解析 → EmotionEventFrame (原始)         │   │
│  │  [ACT:...] 标签 → 解析 → ActionEventFrame (原始)          │   │
│  │  function_call   → 解析 → FunctionCallRouter               │   │
│  └───────────────────────────────────────────────────────────┘   │
│         ↓                                                         │
│  ┌─ EventStabilizer (事件稳定器) ─────────────────────────┐     │
│  │                                                           │     │
│  │  对每种事件类型：                                          │     │
│  │    1. 置信度过滤: < 阈值 → 丢弃                           │     │
│  │    2. 防抖: 在 N ms 内合并同类型事件                       │     │
│  │    3. 阶段逻辑:                                           │     │
│  │       - 首次检测   → stage=pre,  confidence*0.8            │     │
│  │       - 稳定(200ms) → stage=final, confidence*1.0          │     │
│  │       - final 覆盖任何待处理的 pre                         │     │
│  │                                                           │     │
│  │  可按事件类型配置：                                        │     │
│  │    emotion: debounce=200ms, conf_threshold=0.6             │     │
│  │    action:  debounce=300ms, conf_threshold=0.7             │     │
│  │                                                           │     │
│  └───────────────────────────────────────────────────────────┘     │
│         ↓                    ↓                                    │
│  push_frame():         FunctionCallRouter:                        │
│    LLMTextFrame          capture_camera → DeviceCommandFrame      │
│    EmotionEventFrame     switch_scene   → DeviceCommandFrame      │
│    ActionEventFrame      switch_costume → DeviceCommandFrame      │
│                          play_effect    → DeviceCommandFrame      │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

#### LLM 结构化输出格式

LLM 被提示在流式输出中嵌入结构化标记：

```
System Prompt (摘录):
  あなたの返答には、感情と動作のマーカーを含めてください。
  テキスト中に以下の形式で埋め込んでください：

  感情: [EMO:emotion:intensity]  例: [EMO:happy:0.8]
  動作: [ACT:intent:gesture:duration_ms]  例: [ACT:greeting:wave:2000]

  マーカーは文の適切な位置に配置してください。
  マーカーはユーザーには表示されません。
```

LLM 输出流示例：

```
[EMO:happy:0.8]こんにちは！[ACT:greeting:wave:2000]今日はいい天気ですね。
```

StreamParser 在推送 LLMTextFrame 前剥离标记，因此 TTS 接收到的是纯净文本：`こんにちは！今日はいい天気ですね。`

#### Function Call 定义

```python
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "capture_camera",
            "description": "端末のカメラで写真を撮影する。ユーザーが何かを見せたい時、"
                          "または視覚情報が必要な時に使用する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "撮影する理由"
                    }
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "switch_scene",
            "description": "背景シーンを切り替える",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {
                        "type": "string",
                        "enum": ["office", "living_room", "outdoor", "classroom"]
                    }
                },
                "required": ["scene"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "switch_costume",
            "description": "キャラクターの衣装を変更する",
            "parameters": {
                "type": "object",
                "properties": {
                    "costume": {
                        "type": "string",
                        "enum": ["formal", "casual", "kimono", "uniform"]
                    }
                },
                "required": ["costume"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_animation",
            "description": "特定のアニメーションやエフェクトを再生する",
            "parameters": {
                "type": "object",
                "properties": {
                    "animation": {"type": "string"},
                    "target": {"type": "string", "default": "character"}
                },
                "required": ["animation"]
            }
        }
    }
]
```

#### 摄像头拍摄时序

```
t=0s    用户: "これを見てください"
t=0.3s  STT → TranscriptionFrame
t=0.5s  LLM 识别意图 → function_call: capture_camera
          │
          ├─ 推送 DeviceCommandFrame(capture_camera) → 下行至端侧
          └─ 推送 LLMTextFrame("はい、見せてください！") → TTS → 音频下行
                                                            (临时响应)
t=0.8s  端侧接收 capture_camera → Camera2 API → 拍摄 JPEG
t=1.0s  端侧上传: {"type": "image", "data": "<base64>", ...}
          │
          ├─ UESerializer → UserImageRawFrame
          └─ Pipeline 传递至 CustomLLM 上下文
t=1.2s  LLM 在上下文中处理图像 → 生成响应
t=1.5s  LLM: "これは赤いリンゴですね！" → TTS → 音频下行
```

---

### 6.2 Emotion 模块

**职责**：事件 → 驱动指令。不包含语义理解。

**继承**：`FrameProcessor`

**消费**：`EmotionEventFrame`、`ActionEventFrame`、生命周期帧

**产出**：`SetEmotionDriverFrame`、`PlayMotionDriverFrame`、`SetModeDriverFrame`、`SetGazeDriverFrame`

> 注：口唇同步（原 LipsyncDriver）已移至端侧，由 RK3588 从 TTS 音频 PCM 实时分析驱动。

**透传**：`TTSAudioRawFrame`、`DeviceCommandFrame` 及所有其他帧

#### 内部架构

```
┌─── EmotionModule (FrameProcessor) ──────────────────────────────┐
│                                                                   │
│  process_frame(frame, direction):                                 │
│    按 frame 类型路由 ──→ 子模块                                   │
│                                                                   │
│  ┌─ BaseEmotionSM (情感状态机) ──────────────────────────────┐   │
│  │                                                           │    │
│  │  状态:                                                    │    │
│  │    current_emotion: str = "neutral"                       │    │
│  │    target_emotion: str = "neutral"                        │    │
│  │    current_intensity: float = 0.0                         │    │
│  │    target_intensity: float = 0.0                          │    │
│  │    transition_progress: float = 1.0  (0→1 在 fade 期间)  │    │
│  │    fade_duration_ms: int = 300                            │    │
│  │    locked: bool = false                                   │    │
│  │    last_event_time: float                                 │    │
│  │    decay_timeout_s: float = 5.0                           │    │
│  │    speaking: bool = false                                 │    │
│  │                                                           │    │
│  │  on_emotion_event(frame: EmotionEventFrame):              │    │
│  │    if confidence < CONF_THRESHOLD: return                 │    │
│  │    if stage == "pre" and locked: return                   │    │
│  │    target_emotion = frame.emotion                         │    │
│  │    target_intensity = frame.intensity                     │    │
│  │    if stage == "final": locked = true                     │    │
│  │    fade_ms = compute_fade(current → target)               │    │
│  │    → push SetEmotionDriverFrame(                          │    │
│  │        emotion=target, intensity=target_intensity,        │    │
│  │        fade_ms=fade_ms,                                   │    │
│  │        mouth_override=(not speaking))                     │    │
│  │    last_event_time = now()                                │    │
│  │                                                           │    │
│  │  decay_tick(): (定期或在帧到达时调用)                       │    │
│  │    if now() - last_event_time > decay_timeout:            │    │
│  │      locked = false                                       │    │
│  │      target → neutral, intensity → 0.0                    │    │
│  │      → push SetEmotionDriverFrame(neutral, 0, 500, ...)  │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─ MotionController (动作控制器) ────────────────────────────┐  │
│  │                                                           │    │
│  │  状态:                                                    │    │
│  │    current_clip: str = "standing_idle_01"                 │    │
│  │    current_intent: str = "idle"                           │    │
│  │    speaking: bool = false                                 │    │
│  │                                                           │    │
│  │  on_action_event(frame: ActionEventFrame):                │    │
│  │    if confidence < CONF_THRESHOLD: return                 │    │
│  │    if stage == "pre" and current_intent == frame.intent:  │    │
│  │      return  (相同意图，忽略 pre)                          │    │
│  │                                                           │    │
│  │    candidates = motion_tree.query(                        │    │
│  │      intent=frame.intent,                                 │    │
│  │      gesture_hint=frame.gesture_hint,                     │    │
│  │      speaking=speaking,                                   │    │
│  │    )                                                      │    │
│  │                                                           │    │
│  │    plan = transition_planner.plan(                        │    │
│  │      current_clip=current_clip,                           │    │
│  │      candidates=candidates,                               │    │
│  │      constraints={speaking, ...},                         │    │
│  │    )                                                      │    │
│  │                                                           │    │
│  │    current_clip = plan.target_clip                        │    │
│  │    current_intent = frame.intent                          │    │
│  │    → push PlayMotionDriverFrame(plan)                     │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
│  注: LipsyncDriver 已移至端侧（见 §9.1 AudioDrivenLipsync）       │
│                                                                   │
│  ┌─ ModeTracker (模式追踪器) ────────────────────────────────┐   │
│  │                                                           │    │
│  │  on_frame(frame):                                         │    │
│  │    UserStartedSpeakingFrame → mode=LISTENING              │    │
│  │    UserStoppedSpeakingFrame → mode=THINKING               │    │
│  │    BotStartedSpeakingFrame  → mode=SPEAKING               │    │
│  │    BotStoppedSpeakingFrame  → mode=IDLE                   │    │
│  │    → push SetModeDriverFrame(mode)                        │    │
│  │    → 更新 BaseEmotionSM 和 MotionCtrl 中的 speaking 标志  │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

#### Blendshape 冲突解决

由云端 EmotionModule 通过 `mouth_override` 标志 + 端侧 AudioDrivenLipsync 协同控制：

```
说话状态 (mode=SPEAKING):
  SetEmotionDriverFrame → mouth_override = false
    → 端侧仅将表情应用于眼睛、眉毛、脸颊
  AudioDrivenLipsync (端侧本地) → 始终应用于嘴部区域
    → 从 TTS 音频 PCM 实时分析生成口型 blendshape

非说话状态 (mode=IDLE/LISTENING/THINKING):
  SetEmotionDriverFrame → mouth_override = true
    → 端侧将表情应用于整个面部（包括嘴部）
  AudioDrivenLipsync → 自动停止（无音频输入）
```

#### 过渡规划器决策逻辑

```
输入: current_clip, candidates[], constraints

1. 相同意图，仅强度不同？
   → PARAM_MORPH { params: {speed, energy, layer_weight} }

2. 不同意图，片段兼容（相同身体区域，可平滑混合）？
   → CROSS_FADE { to: best_candidate, fadeMs: 300-500 }

3. 不同意图，片段不兼容，有桥接动画？
   → BRIDGE { bridgeClip: matching_bridge, to: target_clip }

4. 不同意图，无桥接，必须走安全路线？
   → SAFE_ROUTE {
       exit: current_clip.safe_exit,
       idle: "standing_idle",
       entry: target_clip.safe_entry,
       to: target_clip
     }
```

---

### 6.3 FishAudioTTSService（日语 TTS）

**职责**：将 LLMTextFrame 转换为日语语音音频流。

**使用**：Pipecat 已有的 `FishAudioTTSService`（`src/pipecat/services/fish/tts.py`）

**协议**：WebSocket 流式（`wss://api.fish.audio/v1/tts/live`），使用 ormsgpack 二进制序列化

#### 选择 Fish Audio 的理由

- **日语原生支持**：高质量日语语音模型
- **WebSocket 流式**：低延迟首字节（无需等待完整语句合成）
- **与 Pipecat 集成**：已有完整的 `InterruptibleTTSService` 实现
- **语音克隆 / 自定义语音**：通过 `model_id` 指定特定语音

#### 关键配置

```python
from pipecat.services.fish.tts import FishAudioTTSService

tts = FishAudioTTSService(
    api_key="...",
    model_id="...",                     # Fish Audio 日语语音模型 ID
    params=FishAudioTTSService.InputParams(
        language=Language.JA_JP,
    ),
)
```

#### 口唇同步方案变更

Fish Audio **不提供 viseme/音素时间数据**（仅返回音频事件），因此口唇同步方案
从云端 viseme 驱动改为 **端侧音频驱动**：

```
原方案 (Azure TTS):
  Cloud: TTS → VisemeEventFrame → EmotionModule.LipsyncDriver
       → SetVisemeDriverFrame → 网络下行 → 端侧 VisemeApplicator

新方案 (Fish Audio):
  Cloud: TTS → TTSAudioRawFrame → 网络下行 → 端侧 AudioPlayback
  Edge:  AudioPlayback → PCM 数据 → AudioDrivenLipsync → 口型 blendshape
         (RK3588 本地实时处理, 零网络延迟)
```

**优势**：
- 消除 viseme 网络传输延迟（原需 50-100ms）
- 口型与音频完美同步（同源数据）
- 简化云端 pipeline（移除 LipsyncDriver 子模块）
- RK3588 NPU 可加速音频分析

---

### 6.4 UE Frame 序列化器

**职责**：为 WebSocket 协议序列化/反序列化帧。

**继承**：`FrameSerializer`

**文件**：`src/pipecat/serializers/ue.py`

```python
class UEFrameSerializer(FrameSerializer):
    """UE 数字人 WebSocket 协议序列化器。

    二进制帧: 音频 PCM 数据
    文本帧: JSON 消息（图像、控制、驱动指令）
    """

    async def serialize(self, frame: Frame) -> str | bytes | None:
        # 音频 → 二进制
        if isinstance(frame, AudioRawFrame):
            return frame.audio

        # Transport 消息（驱动指令、设备指令）→ JSON
        if isinstance(frame, (OutputTransportMessageFrame,
                              OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)

        # InterruptionFrame → JSON
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interrupt"})

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        # 二进制 → 音频
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data,
                sample_rate=self._sample_rate,
                num_channels=1,
            )

        # 文本 → JSON 解析
        message = json.loads(data)
        msg_type = message.get("type")

        if msg_type == "image":
            image_bytes = base64.b64decode(message["data"])
            return UserImageRawFrame(
                image=image_bytes,
                size=(message.get("width", 640), message.get("height", 480)),
                format="image/jpeg",
            )

        if msg_type == "control":
            return InputTransportMessageFrame(message=message)

        return None
```

---

### 6.5 数字人输出处理器

**职责**：将所有自定义 DriverFrame 类型转换为 `OutputTransportMessageFrame` 以便 WebSocket 传输。

**继承**：`FrameProcessor`

```python
class DigitalHumanOutputProcessor(FrameProcessor):
    """将内部 DriverFrame 转换为 OutputTransportMessageFrame。

    此处理器位于 EmotionModule 和 transport output 之间。
    它桥接了内部 pipeline frame 类型和 WebSocket 序列化层的差距。
    """

    FRAME_TO_MESSAGE = {
        SetEmotionDriverFrame: lambda f: {
            "type": "SET_EMOTION",
            "emotion": f.emotion,
            "intensity": f.intensity,
            "fadeMs": f.fade_ms,
            "mouthOverride": f.mouth_override,
        },
        PlayMotionDriverFrame: lambda f: {
            "type": "PLAY_MOTION",
            "plan": {"kind": f.plan_kind, **f.plan_data},
        },
        SetModeDriverFrame: lambda f: {
            "type": "SET_MODE",
            "mode": f.mode,
        },
        SetGazeDriverFrame: lambda f: {
            "type": "SET_GAZE",
            "target": f.target,
            "weight": f.weight,
        },
        DeviceCommandFrame: lambda f: {
            "type": "device_cmd",
            "action": f.action,
            "request_id": f.request_id,
            "params": f.params,
        },
    }

    async def process_frame(self, frame, direction):
        frame_type = type(frame)
        if frame_type in self.FRAME_TO_MESSAGE:
            msg = self.FRAME_TO_MESSAGE[frame_type](frame)
            msg["ts"] = int(time.time() * 1000)
            await self.push_frame(
                OutputTransportMessageFrame(message=msg)
            )
        else:
            await self.push_frame(frame, direction)
```

---

### 6.6 记忆模块

#### MemoryRetriever (记忆检索器)

**职责**：在 LLM 调用前，检索相关记忆并注入上下文。

**继承**：`FrameProcessor`

```
process_frame:
  OpenAILLMContextFrame →
    1. 提取最新用户消息文本
    2. 生成 embedding (text-embedding-3-small, 异步)
    3. 查询 pgvector: 该用户 top-K 相似记忆
       - 过滤: user_id, importance > 阈值
       - 排序: cosine_similarity * recency_weight * importance
       - 超时: 最长 200ms
    4. 查询 Redis: 热记忆缓存（PG 较慢时的后备）
    5. 将记忆作为 system message 注入 LLM 上下文：
       "関連する記憶: {memory1}; {memory2}; ..."
    6. 推送增强后的 OpenAILLMContextFrame 至下游
```

#### MemoryWriterObserver (记忆写入观察者)

**职责**：观察 pipeline 帧流，在 LLM 响应完成后异步提取并存储记忆。

**继承**：`BaseObserver`（不在 pipeline 中，通过 `PipelineTask(observers=[...])` 挂载）

**设计理由**：MemoryWriter 从不修改或阻塞帧流（仅观察 + 异步后台写入），
使用 Observer 模式比 FrameProcessor 更合适：
- 不占用 pipeline 环节，减少帧透传开销
- 符合 Pipecat Observer 的设计意图（监控帧流而不修改 pipeline）
- 即使 Observer 内部出错也不会影响 pipeline 运行

```python
class MemoryWriterObserver(BaseObserver):
    """观察 pipeline 帧流，异步提取和存储记忆。"""

    async def on_push_frame(self, src, frame, direction):
        if isinstance(frame, LLMFullResponseEndFrame):
            # 触发异步任务（非阻塞 pipeline）
            asyncio.create_task(self._extract_and_store(frame))

    async def _extract_and_store(self, frame):
        try:
            # 1. 收集完成的响应文本
            # 2. 基于规则的提取：实体、名称、日期（正则/NER）
            # 3. 可选 LLM 提取：总结关键事实（轻量模型）
            # 4. 为每个提取的事实生成 embedding
            # 5. Upsert 至 memories 表（按相似度去重）
            # 6. 更新 Redis 热缓存
            # 7. 写入消息至 messages 表
            # 8. 在 Redis 中递增 session turn_count
            ...
        except Exception as e:
            logger.error(f"Memory extraction failed: {e}")
            # 静默失败，不影响 pipeline
```

---

### 6.7 场景/服装管理（分散式）

**设计理由**：场景切换是极低频操作（一次会话 0-2 次），不需要占用 pipeline 环节。
原 SceneManager 还存在位置矛盾：它在 CustomLLM 之前，但 LLM 发起的 DeviceCommandFrame
在 CustomLLM 之后产生，永远不会回流。拆散后逻辑更清晰。

场景/服装管理分散到 3 个已有组件中：

#### (1) 端侧发起的切换 → UESerializer + transport 事件层

```python
# UESerializer.deserialize() 中处理
async def deserialize(self, data: str | bytes) -> Frame | None:
    ...
    if msg_type == "control":
        action = message.get("action")
        if action in ("switch_scene", "switch_costume"):
            # 直接在 transport 层处理，不进入 pipeline
            await self._handle_scene_switch(message)
            return None   # 不生成 Frame
        return InputTransportMessageFrame(message=message)

async def _handle_scene_switch(self, message):
    """处理端侧发起的场景/服装切换。"""
    action = message["action"]

    if action == "switch_scene":
        scene = await self._db.fetch_scene(message["scene"])
        await self._redis.hset(f"session:{self._sid}", mapping={
            "scene_id": str(scene.id),
            "scene_name": scene.name,
        })
        # 推送确认指令回端侧
        await self._send_device_cmd({
            "action": "switch_scene",
            "params": {"scene": scene.name, "ue_level": scene.ue_level_name,
                       "transition": "fade"},
        })

    elif action == "switch_costume":
        # 验证场景-服装兼容性 → 加载配置 → 更新 Redis → 推送确认
        ...
```

#### (2) 场景 prompt 注入 → CustomLLM.PromptManager

```python
class PromptManager:
    async def assemble_system_prompt(self, context):
        """组装 system prompt，包含场景/服装特定的 prompt。"""
        # 1. 基础人格 prompt
        prompt = self._base_persona

        # 2. 从 Redis 读取当前场景（一次 HGET，<1ms）
        session = await self._redis.hgetall(f"session:{self._sid}")
        scene_id = session.get("scene_id")
        if scene_id:
            scene_prompt = await self._get_scene_prompt(scene_id)  # 有 Redis 缓存
            prompt += f"\n\n{scene_prompt}"

        # 3. 注入记忆上下文（由 MemoryRetriever 已写入 context）
        # 4. 追加工具定义
        return prompt
```

#### (3) LLM 发起的切换 → CustomLLM.FunctionCallRouter

```python
# FunctionCallRouter 处理 switch_scene / switch_costume function call
async def handle_function_call(self, name, args):
    if name == "switch_scene":
        scene = await self._db.fetch_scene(args["scene"])
        await self._redis.hset(f"session:{self._sid}", mapping={
            "scene_id": str(scene.id),
            "scene_name": scene.name,
        })
        # 推送 DeviceCommandFrame 下行（经 dh_output_processor → transport）
        await self.push_frame(DeviceCommandFrame(
            action="switch_scene",
            request_id=str(uuid4()),
            params={"scene": scene.name, "ue_level": scene.ue_level_name},
        ))
        return {"status": "success", "scene": scene.name}
    ...
```

---

## 7. 数据库设计

### 7.1 设计概述

数据库采用 PostgreSQL + pgvector + Redis 的组合架构：

- **PostgreSQL**: 持久化存储用户数据、会话记录、长期记忆、场景/服装配置等
- **pgvector**: 为 memories 表提供向量相似度检索，支持语义搜索
- **Redis**: 会话状态热缓存、记忆热缓存、设备连接注册

#### 数据分层策略

| 层级 | 存储 | 数据类型 | 生命周期 |
|------|------|----------|----------|
| 工作记忆 | Pipecat LLMContext | 当前对话上下文 | 单次会话 |
| 短期缓存 | Redis | 会话状态、热记忆、设备状态 | TTL 管理（30分钟-1小时）|
| 长期存储 | PostgreSQL | 用户、会话、消息、记忆、配置 | 永久（可按策略清理）|

### 7.2 ER 关系图

```
┌──────────┐    1:N    ┌──────────┐    1:N    ┌──────────┐
│  users   │──────────→│ sessions │──────────→│ messages │
└──────────┘           └──────────┘           └──────────┘
     │                      │
     │ 1:N                  │ N:1
     ↓                      ↓
┌──────────┐          ┌──────────┐
│ memories │          │  scenes  │
└──────────┘          └──────────┘
     │                      │
     │ N:1                  │ M:N
     ↓                      ↓
┌──────────────┐    ┌───────────────────┐    ┌──────────┐
│user_preferences│   │scene_costume_rules│←──│ costumes │
└──────────────┘    └───────────────────┘    └──────────┘

┌──────────────┐    ┌────────────────────┐    ┌─────────────────┐
│ emotion_logs │    │device_command_logs  │    │ prompt_templates │
└──────────────┘    └────────────────────┘    └─────────────────┘

┌──────────────┐    ┌───────────────────┐
│ motion_clips │    │ bridge_animations │
└──────────────┘    └───────────────────┘
```

### 7.3 PostgreSQL 核心表

```sql
-- ================================================================
-- 扩展
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";        -- pgvector

-- ================================================================
-- 用户表 (users)
-- 说明：存储端侧设备绑定的用户信息
-- ================================================================

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id       VARCHAR(128) UNIQUE NOT NULL,   -- 端侧设备唯一标识
    display_name    VARCHAR(64),                     -- 用户显示名
    language        VARCHAR(8) DEFAULT 'ja-JP',      -- 用户语言偏好
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 说明：device_id 是端侧设备的唯一标识，用于 WebSocket 连接时的身份识别和会话恢复。
-- language 默认为日语，未来可扩展多语言支持。

-- ================================================================
-- 会话表 (sessions)
-- 说明：记录每次对话会话的完整信息
-- ================================================================

CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    scene_id        UUID REFERENCES scenes(id),      -- 会话开始时的场景
    costume_id      UUID REFERENCES costumes(id),    -- 会话开始时的服装
    started_at      TIMESTAMPTZ DEFAULT now(),
    ended_at        TIMESTAMPTZ,                     -- 会话结束时间（NULL 表示进行中）
    summary         TEXT,                            -- 会话摘要（结束时由 LLM 生成）
    turn_count      INT DEFAULT 0,                   -- 对话轮次计数
    metadata        JSONB DEFAULT '{}',              -- 扩展字段（如设备信息、网络质量等）
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_sessions_user ON sessions(user_id, started_at DESC);
-- 说明：按 user_id + started_at DESC 索引，支持快速查询用户最近的会话。

-- ================================================================
-- 消息表 (messages)
-- 说明：存储每轮对话的消息内容
-- ================================================================

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,                   -- 消息文本内容
    emotion         VARCHAR(32),                     -- 该消息关联的情感（assistant 消息）
    has_image       BOOLEAN DEFAULT false,           -- 是否包含图像输入
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_session ON messages(session_id, created_at);
-- 说明：按 session_id + created_at 索引，支持按时间顺序查询会话消息。

-- ================================================================
-- 长期记忆表 (memories) - 向量检索
-- 说明：存储从对话中提取的结构化记忆，支持语义搜索
-- ================================================================

CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category        VARCHAR(32) NOT NULL
                    CHECK (category IN ('fact', 'preference', 'summary', 'event')),
                    -- fact: 用户事实（如"用户名叫田中"）
                    -- preference: 用户偏好（如"喜欢猫"）
                    -- summary: 会话摘要
                    -- event: 重要事件（如"用户上周去了京都"）
    content         TEXT NOT NULL,                   -- 记忆文本内容
    embedding       vector(1536),                    -- text-embedding-3-small 向量维度
    importance      FLOAT DEFAULT 0.5
                    CHECK (importance >= 0 AND importance <= 1),
                    -- 重要性评分：0.0-1.0
    source_session  UUID REFERENCES sessions(id),    -- 来源会话
    access_count    INT DEFAULT 0,                   -- 被检索次数（用于热度计算）
    last_accessed   TIMESTAMPTZ,                     -- 最后被检索时间
    created_at      TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ                      -- 过期时间（NULL 表示永不过期）
);

-- 向量相似度索引（IVFFlat，lists 数量根据数据规模调整）
CREATE INDEX idx_memories_embedding
    ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
-- 说明：ivfflat 适合中等规模数据（<100万条），若数据量更大可改用 HNSW 索引。

CREATE INDEX idx_memories_user_category
    ON memories(user_id, category);
-- 说明：按类别查询特定用户的记忆。

CREATE INDEX idx_memories_user_importance
    ON memories(user_id, importance DESC);
-- 说明：按重要性排序查询，用于热缓存预加载。

-- ================================================================
-- 场景表 (scenes)
-- 说明：定义可切换的场景配置
-- ================================================================

CREATE TABLE scenes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(64) NOT NULL UNIQUE,     -- 场景内部名称（如 "office"）
    display_name    VARCHAR(128),                    -- 场景显示名称
    ue_level_name   VARCHAR(128) NOT NULL,           -- UE 关卡名称
    system_prompt   TEXT,                            -- 场景特定的 system prompt 追加内容
    default_camera  JSONB,                           -- 默认摄像机参数
    ambient_config  JSONB,                           -- 环境配置（光照、音效等）
    metadata        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,            -- 是否启用
    sort_order      INT DEFAULT 0,                   -- 排序权重
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ================================================================
-- 服装表 (costumes)
-- 说明：定义可切换的角色服装
-- ================================================================

CREATE TABLE costumes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(64) NOT NULL UNIQUE,     -- 服装内部名称（如 "kimono"）
    display_name    VARCHAR(128),                    -- 服装显示名称
    ue_asset_path   VARCHAR(256) NOT NULL,           -- UE 资源路径
    morph_target_map JSONB,                          -- Morph Target 映射（不同服装可能影响表情权重）
    system_prompt   TEXT,                            -- 服装特定的人格调整 prompt
    metadata        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,
    sort_order      INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ================================================================
-- 场景-服装兼容性规则表 (scene_costume_rules)
-- 说明：定义哪些服装可在哪些场景中使用
-- ================================================================

CREATE TABLE scene_costume_rules (
    scene_id        UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    costume_id      UUID NOT NULL REFERENCES costumes(id) ON DELETE CASCADE,
    is_default      BOOLEAN DEFAULT false,           -- 是否为该场景的默认服装
    PRIMARY KEY (scene_id, costume_id)
);

-- 说明：M:N 关系。若 scene_costume_rules 中无记录，则该服装不允许在该场景中使用。
-- is_default=true 的记录表示切换到该场景时自动选择的服装。
```

### 7.4 扩展表

```sql
-- ================================================================
-- 情感日志表 (emotion_logs)
-- 说明：记录情感事件流水，用于分析和调优
-- ================================================================

CREATE TABLE emotion_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    emotion         VARCHAR(32) NOT NULL,            -- 情感标签
    intensity       FLOAT NOT NULL,                  -- 强度
    confidence      FLOAT NOT NULL,                  -- 置信度
    stage           VARCHAR(8) NOT NULL              -- "pre" 或 "final"
                    CHECK (stage IN ('pre', 'final')),
    source          VARCHAR(16) DEFAULT 'llm'        -- 事件来源（llm / rule / decay）
                    CHECK (source IN ('llm', 'rule', 'decay')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_emotion_logs_session ON emotion_logs(session_id, created_at);
CREATE INDEX idx_emotion_logs_emotion ON emotion_logs(emotion, created_at);

-- 用途：
--   1. 分析情感分布，调优 confidence_threshold
--   2. 分析 pre→final 转化率，优化 debounce 参数
--   3. 识别异常情感模式（如频繁切换）

-- ================================================================
-- 设备指令日志表 (device_command_logs)
-- 说明：记录云端→端侧的指令和响应，用于调试和分析
-- ================================================================

CREATE TABLE device_command_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    request_id      VARCHAR(64) NOT NULL,            -- 请求关联 ID
    action          VARCHAR(64) NOT NULL,            -- 指令动作
    params          JSONB DEFAULT '{}',              -- 指令参数
    status          VARCHAR(16),                     -- 响应状态（success / error / timeout）
    response_data   JSONB,                           -- 响应数据
    latency_ms      INT,                             -- 端侧响应延迟（毫秒）
    created_at      TIMESTAMPTZ DEFAULT now(),
    responded_at    TIMESTAMPTZ                      -- 收到响应时间
);

CREATE INDEX idx_device_cmd_session ON device_command_logs(session_id, created_at);
CREATE INDEX idx_device_cmd_action ON device_command_logs(action, created_at);

-- 用途：
--   1. 监控端侧响应延迟和成功率
--   2. 调试摄像头拍摄、场景切换等异步操作
--   3. 分析 Function Call 的使用频率和效果

-- ================================================================
-- 动作片段表 (motion_clips)
-- 说明：数据库化管理动作片段元数据（与 YAML 配置互补）
-- ================================================================

CREATE TABLE motion_clips (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clip_id         VARCHAR(64) NOT NULL UNIQUE,     -- 片段 ID（对应 motion_tree.yaml）
    category        VARCHAR(32) NOT NULL,            -- 所属类别（idle, greeting 等）
    display_name    VARCHAR(128),
    gesture_hint    VARCHAR(32),                     -- 手势提示
    energy_min      FLOAT DEFAULT 0.0,               -- 能量范围下限
    energy_max      FLOAT DEFAULT 1.0,               -- 能量范围上限
    duration_ms     INT,                             -- 持续时间（毫秒）
    body_parts      TEXT[] DEFAULT '{}',             -- 涉及身体部位
    allow_while_speaking BOOLEAN DEFAULT true,       -- 是否允许在说话时播放
    safe_exit_clip  VARCHAR(64),                     -- 安全退出片段 ID
    safe_entry_clip VARCHAR(64),                     -- 安全进入片段 ID
    ue_montage_path VARCHAR(256),                    -- UE 蒙太奇资源路径
    usage_count     INT DEFAULT 0,                   -- 使用次数统计
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_motion_clips_category ON motion_clips(category, is_active);

-- 用途：
--   1. 运行时查询和过滤可用动作片段
--   2. 统计片段使用频率，避免重复播放
--   3. 管理员后台管理片段（启用/禁用）

-- ================================================================
-- 桥接动画表 (bridge_animations)
-- 说明：定义动作间过渡用的桥接动画
-- ================================================================

CREATE TABLE bridge_animations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bridge_id       VARCHAR(64) NOT NULL UNIQUE,     -- 桥接 ID
    from_body_state VARCHAR(64) NOT NULL,            -- 起始身体状态
    to_body_state   VARCHAR(64) NOT NULL,            -- 目标身体状态
    duration_ms     INT NOT NULL,                    -- 桥接持续时间
    ue_montage_path VARCHAR(256),                    -- UE 蒙太奇资源路径
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX idx_bridge_states
    ON bridge_animations(from_body_state, to_body_state) WHERE is_active;

-- 用途：
--   1. TransitionPlanner 查询可用桥接动画
--   2. 唯一索引确保同一起止状态只有一个活跃桥接

-- ================================================================
-- 用户偏好表 (user_preferences)
-- 说明：存储用户的显式偏好设置（区别于 memories 的隐式提取）
-- ================================================================

CREATE TABLE user_preferences (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key        VARCHAR(64) NOT NULL,            -- 偏好键
    pref_value      JSONB NOT NULL,                  -- 偏好值（JSON 支持复杂类型）
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, pref_key)
);

-- 典型 pref_key 及对应 pref_value：
--   "voice_speed"     : {"value": 1.2}              -- 语速偏好
--   "default_scene"   : {"scene_id": "uuid"}         -- 默认场景
--   "default_costume" : {"costume_id": "uuid"}       -- 默认服装
--   "emotion_sensitivity" : {"value": 0.8}           -- 情感灵敏度
--   "subtitles"       : {"enabled": true}             -- 字幕显示
--   "interaction_mode" : {"mode": "casual"}           -- 互动风格

-- ================================================================
-- Prompt 模板表 (prompt_templates)
-- 说明：管理可配置的 system prompt 模板
-- ================================================================

CREATE TABLE prompt_templates (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(64) NOT NULL UNIQUE,     -- 模板名称
    category        VARCHAR(32) NOT NULL             -- 模板类别
                    CHECK (category IN ('base', 'scene', 'costume', 'memory', 'tool')),
    content         TEXT NOT NULL,                   -- 模板内容（支持变量占位符 {{var}}）
    variables       TEXT[] DEFAULT '{}',             -- 可用变量列表
    version         INT DEFAULT 1,                   -- 版本号
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 示例模板：
-- name: "base_persona"
-- category: "base"
-- content: "あなたは{{character_name}}です。{{character_description}}..."
-- variables: ["character_name", "character_description", "language"]

-- name: "memory_injection"
-- category: "memory"
-- content: "以下はユーザーに関する記憶です：\n{{memories}}\nこれらの記憶を自然に活用してください。"
-- variables: ["memories"]
```

### 7.5 索引策略说明

| 表 | 索引 | 类型 | 用途 |
|----|------|------|------|
| memories | idx_memories_embedding | IVFFlat | 向量相似度搜索（核心检索路径）|
| memories | idx_memories_user_category | B-tree | 按用户+类别过滤 |
| memories | idx_memories_user_importance | B-tree | 按重要性排序的热缓存预加载 |
| sessions | idx_sessions_user | B-tree | 用户最近会话查询 |
| messages | idx_messages_session | B-tree | 会话消息按时间查询 |
| emotion_logs | idx_emotion_logs_session | B-tree | 会话维度情感分析 |
| emotion_logs | idx_emotion_logs_emotion | B-tree | 全局情感分布分析 |
| motion_clips | idx_motion_clips_category | B-tree | 按类别查询可用片段 |
| bridge_animations | idx_bridge_states | B-tree(Unique) | 桥接动画快速查找 |

**向量索引选择指南：**
- 数据量 < 10万条：可使用暴力搜索（无需索引），或使用 IVFFlat(lists=50)
- 数据量 10万-100万条：IVFFlat(lists=100-300)
- 数据量 > 100万条：建议改用 HNSW 索引，查询更快但构建更慢

### 7.6 数据生命周期管理

```sql
-- 定期清理过期记忆
DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < now();

-- 定期清理超过 90 天的情感日志
DELETE FROM emotion_logs WHERE created_at < now() - INTERVAL '90 days';

-- 定期清理超过 30 天的设备指令日志
DELETE FROM device_command_logs WHERE created_at < now() - INTERVAL '30 days';

-- 会话摘要生成（由 MemoryWriter 在会话结束时触发）
UPDATE sessions
SET summary = $1, ended_at = now()
WHERE id = $2;

-- 记忆重要性衰减（定期批处理任务，每天执行）
UPDATE memories
SET importance = importance * 0.98
WHERE last_accessed IS NOT NULL
  AND last_accessed < now() - INTERVAL '7 days'
  AND importance > 0.1;

-- 记忆去重合并（定期批处理任务）
-- 思路：对同一用户的记忆，若两条记忆的余弦相似度 > 0.95，合并为一条
-- 实现：通过应用层代码执行，此处仅示意查询
SELECT m1.id, m2.id,
       1 - (m1.embedding <=> m2.embedding) as similarity
FROM memories m1
JOIN memories m2 ON m1.user_id = m2.user_id AND m1.id < m2.id
WHERE 1 - (m1.embedding <=> m2.embedding) > 0.95;
```

### 7.7 典型查询示例

```sql
-- 1. 语义搜索用户相关记忆（MemoryRetriever 核心查询）
SELECT id, content, category, importance,
       1 - (embedding <=> $1::vector) AS similarity
FROM memories
WHERE user_id = $2
  AND importance > 0.3
  AND (expires_at IS NULL OR expires_at > now())
ORDER BY similarity * importance DESC
LIMIT 5;
-- $1: 当前用户消息的 embedding 向量
-- $2: 用户 ID

-- 2. 查询用户最近 5 次会话摘要
SELECT id, summary, started_at, ended_at, turn_count
FROM sessions
WHERE user_id = $1 AND summary IS NOT NULL
ORDER BY started_at DESC
LIMIT 5;

-- 3. 查询场景可用服装列表
SELECT c.id, c.name, c.display_name, c.ue_asset_path, scr.is_default
FROM costumes c
JOIN scene_costume_rules scr ON c.id = scr.costume_id
WHERE scr.scene_id = $1 AND c.is_active = true
ORDER BY scr.is_default DESC, c.sort_order;

-- 4. 情感分布统计（某个会话）
SELECT emotion, stage,
       COUNT(*) as count,
       AVG(confidence) as avg_confidence,
       AVG(intensity) as avg_intensity
FROM emotion_logs
WHERE session_id = $1
GROUP BY emotion, stage
ORDER BY count DESC;

-- 5. 查询可用的桥接过渡路径
SELECT ba.bridge_id, ba.from_body_state, ba.to_body_state, ba.duration_ms
FROM bridge_animations ba
WHERE ba.from_body_state = $1 AND ba.is_active = true;

-- 6. 获取用户偏好（带默认值回退）
SELECT pref_key, pref_value
FROM user_preferences
WHERE user_id = $1
  AND pref_key = ANY($2::text[]);
```

### 7.8 Redis 结构

```
# ── 活跃会话状态 ──────────────────────────────────
# 说明：存储当前进行中会话的实时状态，Pipeline 各模块读写

HASH  session:{session_id}
  user_id         : UUID              # 用户 ID
  scene_id        : UUID              # 当前场景 ID
  scene_name      : string            # 当前场景名称
  costume_id      : UUID              # 当前服装 ID
  costume_name    : string            # 当前服装名称
  current_emotion : string            # EmotionModule 最新情感
  current_mode    : string            # IDLE / LISTENING / SPEAKING / THINKING
  turn_count      : int               # 对话轮次
  recent_topics   : JSON array        # 最近 5 个话题
  pending_facts   : JSON array        # 待批量写入的事实缓冲
  TTL: 1800 (30 分钟无活动过期)

# ── 用户热记忆缓存 ─────────────────────────────────
# 说明：缓存高重要性记忆，MemoryRetriever 优先查询此处

ZSET  user_memory:{user_id}:hot
  member: JSON {content, category, importance}
  score:  importance * recency_factor
  Max size: 50 entries (通过 ZREMRANGEBYRANK 维护)
  TTL: 3600 (1 小时, 会话开始时刷新)

# ── 设备连接注册表 ────────────────────────────────
# 说明：追踪端侧设备的连接状态

HASH  device:{device_id}
  session_id    : UUID                # 当前关联的会话 ID
  connected_at  : ISO timestamp       # 连接时间
  last_heartbeat: ISO timestamp       # 最后心跳时间
  TTL: 60 (心跳刷新)

# ── Prompt 缓存 ────────────────────────────────────
# 说明：缓存组装好的 prompt，避免重复查询数据库

STRING  prompt_cache:{scene_id}:{costume_id}
  value: 组装好的 system prompt 文本
  TTL: 300 (5 分钟)
```

---

## 8. 配置文件

### 8.1 动作树 (Motion Tree)

```yaml
# config/motion_tree.yaml
# 启动时加载至 EmotionModule.MotionController

categories:

  idle:
    constraints:
      allow_while_speaking: true
      body_parts: [full_body]
    clips:
      - id: standing_idle_01
        energy: [0.0, 0.3]
        safe_exit: null
        safe_entry: null
      - id: breathing_idle_01
        energy: [0.0, 0.2]
        safe_exit: null
        safe_entry: null

  greeting:
    constraints:
      allow_while_speaking: true
      body_parts: [upper_body]
    clips:
      - id: wave_01
        gesture_hint: wave
        energy: [0.5, 1.0]
        safe_exit: wave_exit
        safe_entry: wave_entry
        duration_ms: 2000
      - id: bow_01
        gesture_hint: bow
        energy: [0.3, 0.7]
        safe_exit: bow_exit
        safe_entry: bow_entry
        duration_ms: 1500

  thinking:
    constraints:
      allow_while_speaking: true
      body_parts: [upper_body, head]
    clips:
      - id: chin_touch_01
        gesture_hint: think
        energy: [0.3, 0.6]
        safe_exit: chin_release
        safe_entry: chin_approach
        duration_ms: 3000
      - id: head_tilt_01
        gesture_hint: think
        energy: [0.2, 0.5]
        safe_exit: null
        safe_entry: null
        duration_ms: 2000

  explaining:
    constraints:
      allow_while_speaking: true
      body_parts: [upper_body]
    clips:
      - id: gesture_open_palm_01
        gesture_hint: present
        energy: [0.4, 0.8]
        safe_exit: hands_down
        safe_entry: hands_up
        duration_ms: 2500

  affirming:
    constraints:
      allow_while_speaking: true
      body_parts: [head]
    clips:
      - id: nod_01
        gesture_hint: nod
        energy: [0.3, 0.7]
        safe_exit: null
        safe_entry: null
        duration_ms: 800

  denying:
    constraints:
      allow_while_speaking: true
      body_parts: [head]
    clips:
      - id: head_shake_01
        gesture_hint: shake
        energy: [0.3, 0.7]
        safe_exit: null
        safe_entry: null
        duration_ms: 1000

bridges:
  - id: hand_down_bridge
    from_body_state: hand_raised
    to_body_state: hand_neutral
    duration_ms: 300

  - id: hand_up_bridge
    from_body_state: hand_neutral
    to_body_state: hand_raised
    duration_ms: 300

  - id: chin_release
    from_body_state: chin_touching
    to_body_state: hand_neutral
    duration_ms: 250

  - id: chin_approach
    from_body_state: hand_neutral
    to_body_state: chin_touching
    duration_ms: 250

transition_defaults:
  cross_fade_ms: 400
  param_morph_ms: 200
  safe_route_idle_clip: standing_idle_01
```

### 8.2 Viseme 映射（端侧使用）

```yaml
# config/viseme_mapping.yaml
# 端侧 AudioDrivenLipsync 使用的口型→morph target 映射
# 音素分析结果 → viseme 名称 + morph target 权重

viseme_map:
  0:  {name: "sil",             jaw: 0.00, mouth_open: 0.00, lips_round: 0.00}
  1:  {name: "ae_ax_ah",        jaw: 0.40, mouth_open: 0.50, lips_round: 0.00}
  2:  {name: "aa",              jaw: 0.60, mouth_open: 0.70, lips_round: 0.00}
  3:  {name: "ao",              jaw: 0.50, mouth_open: 0.50, lips_round: 0.30}
  4:  {name: "eh_uh",           jaw: 0.30, mouth_open: 0.35, lips_round: 0.00}
  5:  {name: "er",              jaw: 0.25, mouth_open: 0.25, lips_round: 0.20}
  6:  {name: "y_iy_ih_ix",      jaw: 0.15, mouth_open: 0.15, lips_round: 0.00}
  7:  {name: "w_uw",            jaw: 0.20, mouth_open: 0.15, lips_round: 0.70}
  8:  {name: "ow",              jaw: 0.35, mouth_open: 0.35, lips_round: 0.50}
  9:  {name: "aw",              jaw: 0.55, mouth_open: 0.55, lips_round: 0.30}
  10: {name: "oy",              jaw: 0.40, mouth_open: 0.40, lips_round: 0.50}
  11: {name: "ay",              jaw: 0.50, mouth_open: 0.50, lips_round: 0.00}
  12: {name: "h",               jaw: 0.30, mouth_open: 0.30, lips_round: 0.00}
  13: {name: "r",               jaw: 0.20, mouth_open: 0.20, lips_round: 0.20}
  14: {name: "l",               jaw: 0.20, mouth_open: 0.20, lips_round: 0.00}
  15: {name: "s_z",             jaw: 0.10, mouth_open: 0.05, lips_round: 0.00}
  16: {name: "sh_ch_jh_zh",     jaw: 0.15, mouth_open: 0.10, lips_round: 0.30}
  17: {name: "th_dh",           jaw: 0.15, mouth_open: 0.10, lips_round: 0.00}
  18: {name: "f_v",             jaw: 0.10, mouth_open: 0.05, lips_round: 0.00}
  19: {name: "d_t_n",           jaw: 0.15, mouth_open: 0.10, lips_round: 0.00}
  20: {name: "k_g_ng",          jaw: 0.20, mouth_open: 0.15, lips_round: 0.00}
  21: {name: "p_b_m",           jaw: 0.05, mouth_open: 0.00, lips_round: 0.00}

# 日语特定调整（覆盖默认值）
japanese_overrides:
  # 日语元音: あ(a) い(i) う(u) え(e) お(o)
  # 映射至最接近的 Azure viseme 以适配日语音韵
  2:  {name: "aa",  jaw: 0.55, mouth_open: 0.65, lips_round: 0.00}   # あ
  6:  {name: "ii",  jaw: 0.10, mouth_open: 0.10, lips_round: 0.00}   # い
  7:  {name: "uu",  jaw: 0.15, mouth_open: 0.10, lips_round: 0.65}   # う
  4:  {name: "ee",  jaw: 0.25, mouth_open: 0.30, lips_round: 0.00}   # え
  3:  {name: "oo",  jaw: 0.40, mouth_open: 0.40, lips_round: 0.50}   # お
```

### 8.3 情感配置

```yaml
# config/emotion_config.yaml

base_emotion:
  confidence_threshold: 0.6          # 低于此置信度的情感事件将被丢弃
  decay_timeout_s: 5.0               # 无新事件时回归 neutral 的超时
  default_fade_ms: 300               # 默认过渡时间

  # 特定情感对之间的 fade 时长
  transition_overrides:
    neutral_to_happy: 250
    neutral_to_sad: 400
    happy_to_sad: 500
    angry_to_neutral: 400
    surprised_to_neutral: 200

  # 情感 → 非嘴部 blendshape 默认权重
  blendshape_presets:
    neutral:
      brow_inner_up: 0.0
      brow_outer_up: 0.0
      eye_squint: 0.0
      cheek_squint: 0.0
    happy:
      brow_inner_up: 0.1
      brow_outer_up: 0.2
      eye_squint: 0.3
      cheek_squint: 0.4
    sad:
      brow_inner_up: 0.4
      brow_outer_up: -0.1
      eye_squint: 0.0
      cheek_squint: 0.0
    angry:
      brow_inner_up: -0.3
      brow_outer_up: -0.2
      eye_squint: 0.2
      cheek_squint: 0.0
    surprised:
      brow_inner_up: 0.5
      brow_outer_up: 0.5
      eye_squint: -0.3
      cheek_squint: 0.0
    thinking:
      brow_inner_up: 0.2
      brow_outer_up: 0.1
      eye_squint: 0.1
      cheek_squint: 0.0
```

---

## 9. 端侧架构 (RK3588 + UE5)

### 9.1 UE 应用结构

```
UE5 应用程序 (Android, RK3588)
│
├─ WebSocketClient (C++ 或 Blueprint)
│   ├─ 连接到 wss://cloud-server/ws/digital-human
│   ├─ 发送: audio PCM (二进制), image JPEG (文本), control (文本)
│   └─ 接收: audio PCM (二进制), 驱动指令 (文本)
│
├─ MessageRouter (消息路由器)
│   ├─ 二进制帧 → AudioPlaybackManager
│   └─ 文本帧 → JSON 解析 → CommandDispatcher
│
├─ CommandDispatcher (指令分发器)
│   ├─ SET_EMOTION  → EmotionApplicator
│   ├─ PLAY_MOTION  → MotionExecutor
│   ├─ SET_MODE     → ModeController
│   ├─ SET_GAZE     → GazeController
│   ├─ device_cmd   → DeviceCommandHandler
│   └─ text         → SubtitleDisplay
│
├─ AudioPlaybackManager (音频播放管理器)
│   ├─ PCM 缓冲队列
│   ├─ UAudioComponent 播放
│   └─ 时间戳追踪 (t0 用于 viseme 同步)
│
├─ EmotionApplicator (表情应用器)
│   ├─ 目标 blendshape 权重（来自情感预设）
│   ├─ 平滑插值 (fadeMs)
│   ├─ 区域蒙版: 若 !mouthOverride → 跳过嘴部 blendshape
│   └─ 应用至 SkeletalMeshComponent
│
├─ AudioDrivenLipsync (音频驱动口唇同步, 端侧本地)
│   ├─ 从 AudioPlaybackManager 获取实时 PCM 数据
│   ├─ 音频特征提取 (能量、频谱、过零率)
│   ├─ 音素/口型分类 (轻量模型, 可利用 RK3588 NPU)
│   │   方案 A: 基于规则的能量→开口度映射 (最简单)
│   │   方案 B: 预训练轻量 CNN/RNN 口型分类 (更精确)
│   │   方案 C: OVR LipSync 或类似库 (若有 UE 插件)
│   ├─ 输出: 5 个日语元音口型 (あいうえお) + 闭嘴
│   ├─ Viseme → morph target 权重查找 (config/viseme_mapping.yaml)
│   ├─ Viseme 间平滑插值
│   ├─ 优先级: 活跃时始终覆盖嘴部区域
│   └─ 应用至 SkeletalMeshComponent
│   注: 零网络延迟, 口型与音频完美同步
│
├─ MotionExecutor (动作执行器)
│   ├─ 解析 MotionPlan
│   ├─ CROSS_FADE  → UAnimInstance.Montage_Play with blend
│   ├─ PARAM_MORPH → 调整动画参数 (speed, weight)
│   ├─ BRIDGE      → 播放桥接片段 → 然后目标片段
│   ├─ SAFE_ROUTE  → exit → idle → entry → target (顺序执行)
│   └─ Animation Blueprint 集成
│
├─ ModeController (模式控制器)
│   ├─ IDLE      → 待机动画集, 眨眼, 呼吸
│   ├─ LISTENING → 专注姿态, 微微前倾
│   ├─ THINKING  → 思考动画, 目光移开
│   └─ SPEAKING  → 基础说话姿态, 启用 viseme
│
├─ GazeController (视线控制器)
│   ├─ 基于 IK 的头部/眼球追踪
│   └─ target: "user" → 摄像头方向, "away" → 随机偏移
│
├─ DeviceCommandHandler (设备指令处理器)
│   ├─ capture_camera  → Camera2 API → JPEG → 上传
│   ├─ switch_scene    → Level streaming / 子关卡加载
│   ├─ switch_costume  → 骨骼网格 / 材质切换
│   ├─ play_effect     → Niagara 粒子系统
│   └─ show_ui         → UMG Widget 可见性
│
└─ Digital Human Character (蓝图)
    ├─ SkeletalMeshComponent (自定义模型)
    │   ├─ Morph Targets (嘴部、面部、身体)
    │   └─ Materials (按服装区分)
    ├─ Animation Blueprint
    │   ├─ Montage slots (上半身, 全身)
    │   ├─ Blend spaces
    │   └─ IK chains (视线, 手部)
    └─ Audio Component
```

### 9.2 Blendshape 应用优先级 (UE Tick)

```cpp
void ADigitalHuman::ApplyBlendshapes(float DeltaTime)
{
    // 1. 应用表情至所有 blendshape (来自云端 SET_EMOTION 指令)
    for (auto& [Name, Weight] : EmotionApplicator->GetCurrentWeights())
    {
        if (AudioLipsync->IsActive() && !EmotionApplicator->MouthOverride())
        {
            // 说话期间：跳过嘴部区域 blendshape
            if (IsMouthRegion(Name)) continue;
        }
        Mesh->SetMorphTarget(Name, Weight);
    }

    // 2. 应用音频驱动口型至嘴部 blendshape（端侧本地处理）
    if (AudioLipsync->IsActive())
    {
        for (auto& [Name, Weight] : AudioLipsync->GetCurrentWeights())
        {
            Mesh->SetMorphTarget(Name, Weight);
        }
    }
}
```

---

## 10. 时间同步

### 10.1 音频-口唇同步（端侧本地处理）

```
云端:
  FishAudioTTSService 流式生成 PCM 音频块
  TTSAudioRawFrame = PCM 块按顺序发送（无 viseme 数据）

端侧:
  收到音频块 → AudioPlaybackManager 缓冲+播放
  AudioDrivenLipsync 在播放同时分析 PCM 数据:
    1. 每帧(~16ms) 从播放 buffer 取当前音频窗口
    2. 提取音频特征 (能量、频谱)
    3. 分类口型 (日语5元音 + 闭嘴)
    4. 平滑插值 → 应用至 morph target

  Jitter buffer: 播放前缓冲 2-3 个音频块 (~40-60ms)
  口型延迟: < 1帧 (~16ms, 本地处理无网络延迟)
```

### 10.2 情感/动作时序（发后即忘）

情感和动作指令使用 `fadeMs` 实现平滑过渡。精确时序并不关键 — fade 处理了任何网络抖动。`ts` 字段仅用于排序的单调时间戳。

### 10.3 网络延迟处理

```
上行延迟 (音频):   50-100ms 典型值
下行延迟 (音频):   50-100ms 典型值
下行延迟 (JSON):   50-100ms 典型值

策略:
  - 音频: 端侧 jitter buffer (60ms)
  - 口唇同步: 端侧本地处理, 无网络延迟
  - 情感/动作: 基于 fade, 容忍抖动
  - 模式切换: 立即应用, 无需调度
```

---

## 11. 错误处理与重连

### 11.1 WebSocket 重连 (端侧)

```
连接断开:
  1. UE 检测 WebSocket close/error
  2. 角色进入 "离线" 待机动画
  3. 指数退避重连: 1s, 2s, 4s, 8s, 最大 30s
  4. 重连成功:
     a. 发送 device_id 用于会话恢复
     b. 云端检查 Redis 中的活跃会话
     c. 若会话存在: 恢复（还原场景/服装状态）
     d. 若会话过期: 创建新会话
```

### 11.2 云端 Pipeline 错误

```
STT 错误:    push ErrorFrame(fatal=false), 重试下一个音频块
LLM 错误:    push ErrorFrame(fatal=false), 通过 TTS 发送道歉消息
TTS 错误:    push ErrorFrame(fatal=false), 尝试备用语音
记忆错误:    记录日志, 无记忆继续运行（优雅降级）
致命错误:    push ErrorFrame(fatal=true), 发送 EndFrame, 关闭连接
```

### 11.3 端侧设备错误

```
摄像头拍摄失败: 发送 device_response(status="error")
场景加载失败:   发送 device_response(status="error"), 保持当前场景
音频播放错误:   尝试恢复, 通过 control 消息记录至云端
```

---

## 12. 延迟预算

```
┌─────────────────────────────────────────────────────────┐
│ 端到端: 用户停止说话 → 首个音频播放                       │
│ 目标: < 1.5s                                             │
├──────────────────────────────┬──────────────────────────┤
│ 环节                          │ 预算                     │
├──────────────────────────────┼──────────────────────────┤
│ 音频上行 (网络)               │ 50-100ms                 │
│ VAD 尾部 (语音结束检测)       │ 200-400ms                │
│ STT 最终结果                  │ 100-200ms (流式)         │
│ 记忆检索                      │ < 200ms (含超时)         │
│ LLM 首 token (Gemini 3.0 Flash)│ 150-400ms               │
│ 句子聚合 (日语)               │ 50-100ms (。！？分割)    │
│ TTS 首个音频块 (Fish Audio WS)│ 80-150ms                 │
│ 音频下行 (网络)               │ 50-100ms                 │
│ 端侧 jitter buffer           │ 60ms                     │
├──────────────────────────────┼──────────────────────────┤
│ 总计                          │ ~700-1400ms              │
├──────────────────────────────┴──────────────────────────┤
│ 相比原方案优化点:                                         │
│ - Gemini 3.0 Flash 首 token 更快 (~50ms↓)               │
│ - Fish Audio WebSocket 流式首字节更快 (~50ms↓)           │
│ - 口唇同步无网络延迟 (端侧本地处理)                       │
│ - Pipeline 9 环节 (原 11), 减少帧透传开销                │
│ - 场景切换不经过 pipeline, 端侧响应更快                   │
│ - 情感 pre-event 仍可比音频提前 200-500ms 到达端侧       │
└─────────────────────────────────────────────────────────┘
```

---

## 13. 文件结构

```
src/pipecat/
├── frames/
│   ├── frames.py                      # 已有 frame 定义
│   └── digital_human.py              # 新增: 所有自定义 frame 类型 (§5.2)
│
├── services/
│   ├── azure/
│   │   ├── stt.py                     # 已有 (Azure STT)
│   │   └── common.py                  # 已有
│   └── fish/
│       └── tts.py                     # 已有 (FishAudioTTSService §6.3)
│
├── serializers/
│   ├── base_serializer.py             # 已有
│   └── ue.py                          # 新增: UEFrameSerializer (§6.4)
│
├── processors/
│   └── digital_human/
│       ├── __init__.py
│       ├── custom_llm.py             # 新增: CustomLLMProcessor (§6.1)
│       │                              #   含 PromptManager (场景 prompt 注入)
│       │                              #   含 FunctionCallRouter (场景/服装切换)
│       ├── emotion_module.py         # 新增: EmotionModule (§6.2)
│       ├── output_processor.py       # 新增: DigitalHumanOutputProcessor (§6.5)
│       └── memory_retriever.py       # 新增: MemoryRetriever (§6.6)
│
├── observers/
│   └── digital_human/
│       └── memory_writer.py          # 新增: MemoryWriterObserver (§6.6)
│
├── transports/
│   └── websocket/
│       └── server.py                  # 已有 (原样使用)
│
└── pipeline/
    ├── pipeline.py                    # 已有
    ├── task.py                        # 已有
    └── runner.py                      # 已有

config/
├── motion_tree.yaml                   # 动作树定义 (§8.1)
├── viseme_mapping.yaml                # Viseme 映射 (§8.2)
└── emotion_config.yaml                # 情感状态机配置 (§8.3)

db/
└── migrations/
    └── 001_initial_schema.sql         # PostgreSQL schema (§7.3, §7.4)

examples/
└── digital_human/
    └── server.py                      # 云端服务入口 (§4.3)

tests/
└── test_digital_human/
    ├── test_emotion_module.py
    ├── test_custom_llm.py
    ├── test_ue_serializer.py
    └── test_output_processor.py
```

---

## 14. 实施优先级

| 阶段 | 模块 | 里程碑 |
|------|------|--------|
| **P0** | UESerializer + WebSocket transport + 基础音频往返 | 端侧 ↔ 云端音频通信正常 |
| **P1** | FishAudioTTS + 端侧 AudioDrivenLipsync | TTS 音频正常 + 端侧口唇同步 |
| **P2** | CustomLLM (Gemini 3.0 Flash, 基础) + STT + context aggregation | 语音对话正常 |
| **P3** | EmotionEventFrame + BaseEmotionSM + SetEmotionDriverFrame | 面部表情正常 |
| **P4** | ActionEventFrame + MotionController + TransitionPlanner | 身体动作正常 |
| **P5** | MemoryRetriever + MemoryWriterObserver + DB schema | 跨会话记忆正常 |
| **P6** | 场景/服装 function calls + PromptManager 场景注入 | 场景/服装系统正常 |
| **P7** | EventStabilizer (pre/final) + 防抖 + 置信度调优 | 生产品质打磨 |

---

## 15. Pipeline 优化分析

### 15.1 已应用的优化

#### (1) 端侧音频驱动口唇同步（最大优化项）

```
优化前:
  Cloud TTS (Azure) → VisemeEventFrame → EmotionModule.LipsyncDriver
  → SetVisemeDriverFrame → 网络下行 (50-100ms) → 端侧 VisemeApplicator

优化后:
  Cloud TTS (Fish Audio) → TTSAudioRawFrame → 网络下行 → 端侧播放
  端侧本地: AudioPlayback → PCM → AudioDrivenLipsync → blendshape
```

**收益**：
- 消除 viseme JSON 指令的网络传输（每秒约 15-30 条 SET_VISEME 消息）
- 口型与音频完美同步（同源数据，零传输延迟）
- 降低下行带宽约 30-50%（JSON 指令占比显著）
- 简化云端 pipeline（移除 LipsyncDriver 子模块和相关 Frame 类型）

#### (2) Fish Audio WebSocket 流式 TTS

```
优化前 (Azure TTS):
  HTTP REST 请求 → 等待合成 → 返回音频流
  首字节延迟: 100-200ms

优化后 (Fish Audio):
  WebSocket 持久连接 → ormsgpack 二进制协议 → 即时流式
  首字节延迟: 80-150ms (WebSocket 省去 HTTP 握手开销)
```

**收益**：
- WebSocket 持久连接避免重复 HTTP 握手
- 二进制序列化 (ormsgpack) 比 JSON 更高效
- 首字节延迟改善约 20-50ms

#### (3) Gemini 3.0 Flash 流式 Function Call

```
优化前 (GPT-4o):
  流式输出文本 → 等待 function_call 完整参数 → 触发

优化后 (Gemini 3.0 Flash):
  流式输出文本 → 流式 function_call 参数 → 可更早解析触发
  首 token 延迟通常更低 (~150-400ms vs ~200-500ms)
```

**收益**：
- 流式 function call 参数允许更早触发设备指令
- 原生多模态支持（无需额外编码层处理图像）
- 1M token 上下文窗口，长会话无需截断
- 首 token 延迟改善约 50-100ms

#### (4) EmotionModule 简化

```
优化前:
  EmotionModule 包含 4 个子模块:
    BaseEmotionSM, MotionController, LipsyncDriver, ModeTracker

优化后:
  EmotionModule 包含 3 个子模块:
    BaseEmotionSM, MotionController, ModeTracker
    (LipsyncDriver 移至端侧)
```

**收益**：
- 减少 EmotionModule 的 CPU 开销（不再处理高频 viseme 事件）
- 减少内存占用（移除 viseme 映射表和缓冲队列）
- 代码复杂度降低，更易维护

#### (5) SceneManager 拆散（消除 pipeline 环节）

```
优化前:
  Pipeline: ... → context_aggregator.user() → SceneManager → MemoryRetriever → CustomLLM → ...
  问题 1: 低频操作（一次会话 0-2 次）占用高频帧透传路径
  问题 2: LLM 发起的 DeviceCommandFrame 在 CustomLLM 之后产生，
          永远回不到位于其前方的 SceneManager

优化后:
  Pipeline: ... → context_aggregator.user() → MemoryRetriever → CustomLLM → ...
  端侧发起 → UESerializer + transport 事件层直接处理（不进入 pipeline）
  场景 prompt → CustomLLM.PromptManager 内部从 Redis 读取注入
  LLM 发起  → CustomLLM.FunctionCallRouter 处理 + DeviceCommandFrame 下行
```

**收益**：
- Pipeline 减少一个环节（每帧少一次 isinstance + 透传）
- 消除位置矛盾，逻辑更内聚
- 低频操作不阻塞高频帧路径
- 端侧场景切换响应更快（不需要经过 STT → Aggregator 路径）

#### (6) MemoryWriter → Observer 模式

```
优化前:
  Pipeline: ... → CustomLLM → MemoryWriter → TTS → ...
  MemoryWriter 对每帧: isinstance 检查 → 全部透传（除 LLMFullResponseEndFrame）

优化后:
  Pipeline: ... → CustomLLM → TTS → ...
  MemoryWriterObserver 通过 PipelineTask(observers=[...]) 挂载
  仅在 on_push_frame 回调中异步触发记忆提取
```

**收益**：
- Pipeline 再减一个环节
- Observer 内部异常不影响 pipeline 运行（隔离性更好）
- 符合 Pipecat Observer 设计意图：监控帧流但不修改 pipeline
- 与 MemoryRetriever（必须在 pipeline 中修改 context）形成正确的分工

#### Pipeline 环节精简总结

```
原始 pipeline (11 个环节):
  input → STT → user_agg → SceneManager → MemoryRetriever
  → CustomLLM → MemoryWriter → TTS → EmotionModule
  → OutputProcessor → output → assistant_agg

优化后 pipeline (9 个环节):
  input → STT → user_agg → MemoryRetriever
  → CustomLLM → TTS → EmotionModule
  → OutputProcessor → output → assistant_agg

  + MemoryWriterObserver (observer, 不在 pipeline 中)
  + 场景切换 (transport 事件层, 不在 pipeline 中)
```

### 15.2 延迟对比总结

| 环节 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| LLM 首 token | 200-500ms | 150-400ms | ~50-100ms |
| TTS 首音频块 | 100-200ms | 80-150ms | ~20-50ms |
| 口唇同步延迟 | 50-100ms (网络) | <16ms (本地) | ~50-90ms |
| 下行带宽 | 音频 + viseme JSON + 指令 JSON | 音频 + 指令 JSON | ~30-50%↓ |
| Pipeline 环节数 | 11 | 9 | 2 个环节↓ |
| 端到端总延迟 | ~800-1500ms | ~700-1400ms | ~100ms |

### 15.3 未来可进一步优化的方向

#### (1) MemoryRetriever 并行化

当前 MemoryRetriever 在 pipeline 串行路径中，阻塞 LLM 调用。可考虑：

```python
# 方案: 将记忆检索与 LLM prompt 组装并行化
# 使用 Pipecat 的 ParallelPipeline 机制

parallel_pre_llm = ParallelPipeline(
    [memory_retriever],    # 路径 A: 记忆检索
    [prompt_assembler],    # 路径 B: prompt 模板组装
)
# 两路结果合并后再送入 CustomLLM
```

> 注: 当前已有 200ms 超时机制，此优化仅在记忆检索成为瓶颈时才有必要。

#### (2) TTS 预热连接

Fish Audio 使用 WebSocket 持久连接，但首次建连仍有开销。可在 pipeline 启动时预热：

```python
async def start(self, frame: StartFrame):
    await super().start(frame)
    # 预热 Fish Audio WebSocket 连接
    await self._tts.connect()
```

#### (3) 句子级并行 TTS

日语有明确的句子分隔符（。！？），可在收到第一个句子后立即开始 TTS，
同时 LLM 继续生成后续内容：

```
LLM 流式: "こんにちは。" → 立即送 TTS
LLM 继续: "今日はいい天気ですね。" → 第二次 TTS
```

> 注: Pipecat 的 SentenceAggregator 已支持此模式，默认行为。

#### (4) 端侧 AudioDrivenLipsync 利用 RK3588 NPU

RK3588 的 NPU (6 TOPS) 可用于加速口唇分析模型推理：

```
方案: 将轻量口型分类模型 (如 MobileNet-based) 转换为 RKNN 格式
     部署在 NPU 上运行，CPU 开销趋近于零
```

#### (5) 情感事件批量传输

当 LLM 在短时间内产生多个情感/动作事件时，可合并为一个下行消息：

```json
{"type": "BATCH", "commands": [
    {"type": "SET_EMOTION", "emotion": "happy", "intensity": 0.8, "fadeMs": 300},
    {"type": "PLAY_MOTION", "plan": {"kind": "CROSS_FADE", "to": "wave_01", "fadeMs": 400}}
], "ts": 1708901234567}
```

**收益**: 减少 WebSocket 消息数量，降低端侧解析开销。

#### (6) STT 流式结果与记忆检索重叠

当前: STT 最终结果 → MemoryRetriever 开始检索（串行等待）。
可在 STT 产出高置信度中间结果时，提前触发记忆预检索：

```
STT interim (confidence>0.8): "京都に行った" → 预检索记忆
STT final:                    "京都に行ったことある？" → 用预检索结果（若匹配）或重新检索

预检索命中率约 60-70%（日语句尾变化有限），
命中时可节省 100-150ms（记忆检索时间与 STT 尾部并行）
```

> 注: 需要修改 MemoryRetriever 支持预检索 + 结果缓存 + 失效判断。
> 复杂度较高，建议在 P7 阶段评估。

#### (7) Embedding 本地化

当前 MemoryRetriever 调用远程 API 生成 embedding（text-embedding-3-small）。
可替换为本地轻量 embedding 模型：

```
远程 API:   50-100ms 网络延迟 + 计费
本地模型:   10-30ms (CPU) / 5-15ms (GPU)

候选模型:
  - sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (420MB, 多语言)
  - intfloat/multilingual-e5-small (118MB, 轻量)
```

**收益**: 消除 embedding 网络延迟，记忆检索总时间从 ~200ms 降至 ~50ms。
**代价**: 需要 GPU 内存，且向量质量可能略低于 OpenAI embedding。
