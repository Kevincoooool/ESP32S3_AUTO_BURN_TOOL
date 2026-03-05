# Digital Human System Architecture

> RK3588 + Unreal Engine + Pipecat Cloud Pipeline
> Real-time Japanese Voice Conversation with Lip Sync, Expression & Motion

---

## 1. Overview

### 1.1 Goals

Build a real-time digital human system with:

- Free-form Japanese voice conversation
- Audio-driven real-time lip sync on edge device
- Emotion-driven facial expressions with state machine
- Intent-driven body motion with transition planning
- Scene switching and costume changing
- Cross-session memory with vector retrieval
- Cloud LLM control over edge devices (camera capture, scene/costume commands)

### 1.2 Design Principles

- **LLM Module**: Semantic input → structured events only. No rendering logic.
- **Emotion Module**: Events → driver commands only. No semantic understanding.
- **Edge (UE)**: Pure executor. Receives commands, renders, no decision-making.
- **Frame = Event**: Pipecat's frame pipeline IS the event bus. No external pub/sub needed.
- **pre/final staging**: Predictive events enable early response; final events lock state.

### 1.3 Tech Stack

| Layer | Technology |
|-------|-----------|
| Edge Hardware | RK3588 (Android) |
| Edge Rendering | Unreal Engine 5 (custom digital human model) |
| Cloud Framework | Pipecat (Python, frame-based pipeline) |
| Transport | WebSocket (public network) |
| STT | Azure Speech (Japanese streaming) |
| LLM | Custom module (Gemini 3.0 Flash multimodal + function calling) |
| TTS | Fish Audio (Japanese streaming WebSocket) |
| Edge Lip Sync | Audio-driven lipsync (RK3588 local processing) |
| Database | PostgreSQL + pgvector |
| Cache | Redis |

---

## 2. System Architecture

### 2.1 Deployment Topology

```
┌─── RK3588 Edge Device (Android + UE5) ───┐
│                                            │
│  Mic / Speaker / Camera / HDMI Display     │
│           ↕                                │
│  UE Application                            │
│  ├─ WebSocket Client                       │
│  ├─ CommandDispatcher                      │
│  ├─ Audio Playback                         │
│  ├─ Morph Target Controller                │
│  ├─ Animation Blueprint                    │
│  └─ UI Layer                               │
│                                            │
└──────────────┬─────────────────────────────┘
               │ WebSocket (wss://)
               │ Public Network
               │
┌──────────────┴─────────────────────────────┐
│           Cloud Server                      │
│                                             │
│  ┌─ Pipecat Pipeline (9 stages) ─────────┐ │
│  │ Transport.Input → STT → Aggregator    │ │
│  │ → MemoryRetriever → CustomLLM → TTS   │ │
│  │ → EmotionModule → OutputProcessor     │ │
│  │ → Transport.Output → Aggregator       │ │
│  │                                        │ │
│  │ Observer: MemoryWriterObserver         │ │
│  └───────────────────────────────────────┘ │
│                                             │
│  ┌─ Storage ────────────────────────────┐  │
│  │ PostgreSQL + pgvector │ Redis         │  │
│  └───────────────────────────────────────┘ │
│                                             │
│  ┌─ Cloud AI Services (intranet) ───────┐  │
│  │ Azure STT │ Fish Audio │ Gemini      │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### 2.2 Data Flow Overview

```
           Uplink (Edge → Cloud)                Downlink (Cloud → Edge)
         ┌─────────────────────┐              ┌──────────────────────┐
         │ audio (binary PCM)  │              │ audio (binary PCM)   │
         │ image (JSON+base64) │              │ SET_EMOTION (JSON)   │
         │ control (JSON)      │              │ SET_VISEME  (JSON)   │
         └─────────────────────┘              │ PLAY_MOTION (JSON)   │
                                              │ SET_MODE    (JSON)   │
                                              │ SET_GAZE    (JSON)   │
                                              │ device_cmd  (JSON)   │
                                              │ scene/costume (JSON) │
                                              └──────────────────────┘
```

---

## 3. WebSocket Protocol

Single bidirectional WebSocket connection per device. Binary frames for audio, text frames for JSON messages.

### 3.1 Uplink Messages (Edge → Cloud)

#### Audio (Binary Frame)

Raw PCM audio stream from microphone.

```
Format: PCM 16-bit signed little-endian, mono
Sample Rate: 16000 Hz
Chunk Size: 20ms (640 bytes)
```

#### Image (Text Frame, triggered on demand)

```json
{
    "type": "image",
    "data": "<base64 encoded JPEG>",
    "width": 640,
    "height": 480,
    "trigger": "llm_request | user_button | sensor"
}
```

#### Control (Text Frame)

```json
{"type": "control", "action": "interrupt"}
{"type": "control", "action": "switch_scene", "scene": "office"}
{"type": "control", "action": "switch_costume", "costume": "kimono"}
{"type": "control", "action": "device_response",
 "request_id": "uuid", "status": "success", "data": {...}}
```

### 3.2 Downlink Messages (Cloud → Edge)

#### Audio (Binary Frame)

TTS audio for playback.

```
Format: PCM 16-bit signed little-endian, mono
Sample Rate: 24000 Hz
```

#### Driver Commands (Text Frame)

```json
{"type": "SET_EMOTION",
 "emotion": "happy", "intensity": 0.8,
 "fadeMs": 300, "mouthOverride": false, "ts": 1708901234567}

{"type": "SET_VISEME",
 "viseme": "PP", "weight": 0.85, "audioTs": 0.234}

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

#### Device Commands (Text Frame)

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

#### Text Display (Text Frame, optional for subtitles)

```json
{"type": "text", "text": "こんにちは", "role": "assistant", "final": true}
```

---

## 4. Cloud Pipeline Design

### 4.1 Pipeline Structure

```python
pipeline = Pipeline([
    ws_transport.input(),              # UESerializer deserializes uplink
    stt,                               # Azure STT Japanese (streaming)
    context_aggregator.user(),         # User turn aggregation (text + images)

    scene_manager,                     # Handle edge-initiated scene/costume control
    memory_retriever,                  # Query memories → inject into LLM context

    custom_llm,                        # LLM Module: semantic → structured events
                                       #   outputs: LLMTextFrame
                                       #            EmotionEventFrame
                                       #            ActionEventFrame
                                       #            DeviceCommandFrame (function calls)

    memory_writer,                     # Async: extract facts → write to DB (non-blocking)

    tts,                               # AzureVisemeTTSService
                                       #   consumes: LLMTextFrame
                                       #   produces: TTSAudioRawFrame, VisemeEventFrame
                                       #   passes through: EmotionEventFrame, ActionEventFrame

    emotion_module,                    # Emotion Module: events → driver commands
                                       #   consumes: EmotionEventFrame, ActionEventFrame,
                                       #             VisemeEventFrame, lifecycle frames
                                       #   produces: SetEmotionDriverFrame, PlayMotionDriverFrame,
                                       #             SetVisemeDriverFrame, SetModeDriverFrame
                                       #   passes through: TTSAudioRawFrame

    dh_output_processor,               # All DriverFrames → OutputTransportMessageFrame (JSON)
                                       # DeviceCommandFrame → OutputTransportMessageFrame (JSON)

    ws_transport.output(),             # UESerializer serializes downlink
    context_aggregator.assistant(),    # Assistant turn aggregation
])
```

### 4.2 Frame Flow Diagram

```
ws_transport.input()
  │  InputAudioRawFrame (from binary)
  │  UserImageRawFrame (from JSON image, on-demand)
  │  InputTransportMessageFrame (from JSON control)
  ↓
stt
  │  TranscriptionFrame
  │  (passes through: UserImageRawFrame, InputTransportMessageFrame)
  ↓
context_aggregator.user()
  │  OpenAILLMContextFrame (text + optional images)
  │  (passes through: InputTransportMessageFrame)
  ↓
scene_manager
  │  (consumes: InputTransportMessageFrame with scene/costume actions)
  │  (produces: OutputTransportMessageFrame for scene/costume switch)
  │  (passes through: OpenAILLMContextFrame, updates LLM context if scene has prompt)
  ↓
memory_retriever
  │  (enriches: OpenAILLMContextFrame with retrieved memories)
  ↓
custom_llm
  │  LLMTextFrame (streaming text chunks, metadata stripped)
  │  EmotionEventFrame (emotion, intensity, confidence, stage)
  │  ActionEventFrame (intent, gesture_hint, confidence, timing, stage)
  │  DeviceCommandFrame (capture_camera, play_effect, etc.)
  │  FunctionCallInProgressFrame / FunctionCallResultFrame
  ↓
memory_writer
  │  (async background: extracts facts from completed response)
  │  (passes through: all frames unchanged)
  ↓
tts (AzureVisemeTTSService)
  │  TTSStartedFrame
  │  TTSAudioRawFrame (audio chunks)
  │  VisemeEventFrame (viseme_id + audio_offset)
  │  TTSStoppedFrame
  │  (passes through: EmotionEventFrame, ActionEventFrame, DeviceCommandFrame)
  ↓
emotion_module
  │  SetEmotionDriverFrame (from EmotionEventFrame)
  │  PlayMotionDriverFrame (from ActionEventFrame)
  │  SetVisemeDriverFrame (from VisemeEventFrame)
  │  SetModeDriverFrame (from lifecycle frames)
  │  (passes through: TTSAudioRawFrame, DeviceCommandFrame)
  ↓
dh_output_processor
  │  OutputTransportMessageFrame (JSON for each DriverFrame)
  │  OutputTransportMessageFrame (JSON for DeviceCommandFrame)
  │  (passes through: TTSAudioRawFrame → handled by transport audio path)
  ↓
ws_transport.output()
  │  Binary WebSocket frame (audio)
  │  Text WebSocket frame (JSON commands)
  ↓
context_aggregator.assistant()
```

### 4.3 Server Entry Point

```python
# server.py - Cloud server application

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
        api_key=...,
        tools=TOOL_DEFINITIONS,
        system_prompt=BASE_SYSTEM_PROMPT,
    )

    tts = AzureVisemeTTSService(
        api_key=..., region=...,
        voice="ja-JP-NanamiNeural",
        params=AzureBaseTTSService.InputParams(language=Language.JA_JP),
    )

    context_aggregator = custom_llm.create_context_aggregator()

    pipeline = Pipeline([
        ws_transport.input(),
        stt,
        context_aggregator.user(),
        SceneManager(db=db, redis=redis),
        MemoryRetriever(db=db, redis=redis, timeout_ms=200),
        custom_llm,
        MemoryWriter(db=db, redis=redis),
        tts,
        EmotionModule(config=load_motion_config()),
        DigitalHumanOutputProcessor(),
        ws_transport.output(),
        context_aggregator.assistant(),
    ])

    return pipeline

@app.websocket("/ws/digital-human")
async def websocket_endpoint(websocket: WebSocket):
    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            serializer=UEFrameSerializer(),
        ),
    )

    pipeline = await create_pipeline(transport)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
    )

    runner = PipelineRunner()
    await runner.run(task)
```

---

## 5. Frame Type Definitions

### 5.1 Frame Hierarchy

```
Frame (base)
├── SystemFrame (high priority, not affected by interruptions)
│   ├── InputAudioRawFrame          [existing]
│   ├── InputImageRawFrame          [existing]
│   ├── InputTransportMessageFrame  [existing]
│   └── InterruptionFrame           [existing]
│
├── DataFrame (processed in order, cancelled by interruptions)
│   ├── LLMTextFrame                [existing]
│   ├── TTSAudioRawFrame            [existing]
│   ├── OutputTransportMessageFrame [existing]
│   ├── EmotionEventFrame           [NEW]
│   ├── ActionEventFrame            [NEW]
│   ├── VisemeEventFrame            [NEW]
│   ├── DeviceCommandFrame          [NEW]
│   ├── DeviceResponseFrame         [NEW]
│   ├── SetEmotionDriverFrame       [NEW]
│   ├── PlayMotionDriverFrame       [NEW]
│   ├── SetVisemeDriverFrame        [NEW]
│   ├── SetModeDriverFrame          [NEW]
│   └── SetGazeDriverFrame          [NEW]
│
└── ControlFrame (processed in order, control signals)
    ├── TTSStartedFrame             [existing]
    ├── TTSStoppedFrame             [existing]
    ├── UserStartedSpeakingFrame    [existing]
    ├── UserStoppedSpeakingFrame    [existing]
    ├── BotStartedSpeakingFrame     [existing]
    └── BotStoppedSpeakingFrame     [existing]
```

### 5.2 LLM Output Event Frames

```python
# src/pipecat/frames/digital_human.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pipecat.frames.frames import DataFrame


# ── Layer 1: LLM → Emotion Module ──────────────────────────

@dataclass
class EmotionEventFrame(DataFrame):
    """Emotion event produced by CustomLLM during streaming.

    Parameters:
        emotion: Discrete emotion label.
        intensity: Continuous intensity 0.0-1.0.
        confidence: Model confidence 0.0-1.0.
        stage: "pre" (predictive, revocable) or "final" (confirmed, locked).
    """
    emotion: str = "neutral"
    intensity: float = 0.5
    confidence: float = 0.5
    stage: str = "pre"


@dataclass
class ActionEventFrame(DataFrame):
    """Action/gesture event produced by CustomLLM during streaming.

    Parameters:
        intent: Semantic intent category (e.g., "greeting", "thinking").
        gesture_hint: Suggested gesture (e.g., "wave", "nod").
        confidence: Model confidence 0.0-1.0.
        timing_start_offset_ms: Start offset relative to current utterance.
        timing_duration_ms: Suggested duration.
        stage: "pre" (predictive) or "final" (confirmed).
    """
    intent: str = ""
    gesture_hint: str = ""
    confidence: float = 0.5
    timing_start_offset_ms: int = 0
    timing_duration_ms: int = 2000
    stage: str = "pre"


@dataclass
class VisemeEventFrame(DataFrame):
    """Viseme event produced by AzureVisemeTTSService.

    Parameters:
        viseme_id: Azure Viseme ID (0-21).
        audio_offset: Time offset in seconds relative to current utterance audio start.
    """
    viseme_id: int = 0
    audio_offset: float = 0.0


@dataclass
class DeviceCommandFrame(DataFrame):
    """Command from cloud LLM to edge device (via function call).

    Parameters:
        action: Command action identifier.
        request_id: Unique ID for request-response correlation.
        params: Command-specific parameters.
    """
    action: str = ""
    request_id: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceResponseFrame(DataFrame):
    """Response from edge device to a DeviceCommand.

    Parameters:
        action: Original command action.
        request_id: Correlation ID matching the original command.
        status: "success" or "error".
        data: Response payload.
    """
    action: str = ""
    request_id: str = ""
    status: str = "success"
    data: Optional[Dict[str, Any]] = None


# ── Layer 2: Emotion Module → Edge Renderer ─────────────────

@dataclass
class SetEmotionDriverFrame(DataFrame):
    """Drive facial expression on edge renderer.

    Parameters:
        emotion: Target emotion.
        intensity: Target intensity 0.0-1.0.
        fade_ms: Transition duration in milliseconds.
        mouth_override: If false, only apply to non-mouth blendshapes
                        (mouth is controlled by viseme during speech).
    """
    emotion: str = "neutral"
    intensity: float = 0.5
    fade_ms: int = 300
    mouth_override: bool = True


@dataclass
class PlayMotionDriverFrame(DataFrame):
    """Drive body motion/gesture on edge renderer.

    Parameters:
        plan_kind: Transition type.
        plan_data: MotionPlan parameters, structure depends on plan_kind.
    """
    plan_kind: str = "CROSS_FADE"
    plan_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SetVisemeDriverFrame(DataFrame):
    """Drive lip sync on edge renderer.

    Parameters:
        viseme: Viseme name (e.g., "PP", "FF", "AA").
        weight: Blend weight 0.0-1.0.
        audio_ts: Audio timestamp in seconds for synchronization.
    """
    viseme: str = "sil"
    weight: float = 0.0
    audio_ts: float = 0.0


@dataclass
class SetModeDriverFrame(DataFrame):
    """Drive overall character state on edge renderer.

    Parameters:
        mode: Character mode.
    """
    mode: str = "IDLE"


@dataclass
class SetGazeDriverFrame(DataFrame):
    """Drive gaze direction on edge renderer.

    Parameters:
        target: Gaze target identifier.
        weight: Blend weight 0.0-1.0.
    """
    target: str = "user"
    weight: float = 1.0
```

---

## 6. Module Specifications

### 6.1 CustomLLM Module

**Responsibility**: Semantic input → structured events. Nothing else.

**Extends**: `FrameProcessor`

**Consumes**: `OpenAILLMContextFrame`

**Produces**: `LLMTextFrame`, `EmotionEventFrame`, `ActionEventFrame`, `DeviceCommandFrame`

#### Internal Architecture

```
┌─── CustomLLMProcessor ──────────────────────────────────────────┐
│                                                                   │
│  OpenAILLMContextFrame                                            │
│         ↓                                                         │
│  ┌─ PromptManager ──────────────────────────────────────────┐    │
│  │  Assembles system prompt:                                 │    │
│  │    base_persona + scene_prompt + memory_context + tools   │    │
│  └───────────────────────────────────────────────────────────┘    │
│         ↓                                                         │
│  ┌─ LLM API Call (streaming) ────────────────────────────────┐   │
│  │  model: configurable (gpt-4o / claude / deepseek / etc.)  │   │
│  │  tools: TOOL_DEFINITIONS                                   │   │
│  │  stream: true                                              │   │
│  └───────────────────────────────────────────────────────────┘   │
│         ↓                                                         │
│  ┌─ StreamParser ────────────────────────────────────────────┐   │
│  │  Token accumulator scans for structured markers:           │   │
│  │                                                            │   │
│  │  Plain text     → buffer → LLMTextFrame                    │   │
│  │  [EMO:...] tag  → parse → EmotionEventFrame (raw)          │   │
│  │  [ACT:...] tag  → parse → ActionEventFrame (raw)           │   │
│  │  function_call  → parse → FunctionCallRouter                │   │
│  └───────────────────────────────────────────────────────────┘   │
│         ↓                                                         │
│  ┌─ EventStabilizer ────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  For each event type:                                     │    │
│  │    1. Confidence filter: < threshold → discard            │    │
│  │    2. Debounce: merge same-type events within N ms        │    │
│  │    3. Stage logic:                                        │    │
│  │       - First detection  → stage=pre,  confidence*0.8     │    │
│  │       - Stable (200ms)   → stage=final, confidence*1.0    │    │
│  │       - final overrides any pending pre                   │    │
│  │                                                           │    │
│  │  Configurable per event type:                             │    │
│  │    emotion: debounce=200ms, conf_threshold=0.6            │    │
│  │    action:  debounce=300ms, conf_threshold=0.7            │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│         ↓                    ↓                                    │
│  push_frame():         FunctionCallRouter:                        │
│    LLMTextFrame          capture_camera → DeviceCommandFrame      │
│    EmotionEventFrame     switch_scene   → DeviceCommandFrame      │
│    ActionEventFrame      switch_costume → DeviceCommandFrame      │
│                          play_effect    → DeviceCommandFrame      │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

#### LLM Structured Output Format

The LLM is prompted to embed structured markers in its streaming output:

```
System Prompt (excerpt):
  あなたの返答には、感情と動作のマーカーを含めてください。
  テキスト中に以下の形式で埋め込んでください：

  感情: [EMO:emotion:intensity]  例: [EMO:happy:0.8]
  動作: [ACT:intent:gesture:duration_ms]  例: [ACT:greeting:wave:2000]

  マーカーは文の適切な位置に配置してください。
  マーカーはユーザーには表示されません。
```

Example LLM output stream:

```
[EMO:happy:0.8]こんにちは！[ACT:greeting:wave:2000]今日はいい天気ですね。
```

StreamParser strips markers from text before pushing LLMTextFrame, so TTS receives clean text: `こんにちは！今日はいい天気ですね。`

#### Function Call Definitions

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

#### Camera Capture Sequence

```
t=0s    User: "これを見てください"
t=0.3s  STT → TranscriptionFrame
t=0.5s  LLM recognizes intent → function_call: capture_camera
          │
          ├─ Push DeviceCommandFrame(capture_camera) → downlink to edge
          └─ Push LLMTextFrame("はい、見せてください！") → TTS → audio downlink
                                                            (interim response)
t=0.8s  Edge receives capture_camera → Camera2 API → capture JPEG
t=1.0s  Edge uploads: {"type": "image", "data": "<base64>", ...}
          │
          ├─ UESerializer → UserImageRawFrame
          └─ Pipeline delivers to CustomLLM context
t=1.2s  LLM processes image in context → generates response
t=1.5s  LLM: "これは赤いリンゴですね！" → TTS → audio downlink
```

---

### 6.2 Emotion Module

**Responsibility**: Events → driver commands. No semantic understanding.

**Extends**: `FrameProcessor`

**Consumes**: `EmotionEventFrame`, `ActionEventFrame`, `VisemeEventFrame`, lifecycle frames

**Produces**: `SetEmotionDriverFrame`, `PlayMotionDriverFrame`, `SetVisemeDriverFrame`, `SetModeDriverFrame`, `SetGazeDriverFrame`

**Passes through**: `TTSAudioRawFrame`, `DeviceCommandFrame`, all other frames

#### Internal Architecture

```
┌─── EmotionModule (FrameProcessor) ──────────────────────────────┐
│                                                                   │
│  process_frame(frame, direction):                                 │
│    route by frame type ──→ submodule                              │
│                                                                   │
│  ┌─ BaseEmotionSM ──────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  State:                                                   │    │
│  │    current_emotion: str = "neutral"                       │    │
│  │    target_emotion: str = "neutral"                        │    │
│  │    current_intensity: float = 0.0                         │    │
│  │    target_intensity: float = 0.0                          │    │
│  │    transition_progress: float = 1.0  (0→1 during fade)   │    │
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
│  │  decay_tick():  (called periodically or on frame arrival) │    │
│  │    if now() - last_event_time > decay_timeout:            │    │
│  │      locked = false                                       │    │
│  │      target → neutral, intensity → 0.0                    │    │
│  │      → push SetEmotionDriverFrame(neutral, 0, 500, ...)  │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─ MotionController ───────────────────────────────────────┐    │
│  │                                                           │    │
│  │  State:                                                   │    │
│  │    current_clip: str = "standing_idle_01"                 │    │
│  │    current_intent: str = "idle"                           │    │
│  │    speaking: bool = false                                 │    │
│  │                                                           │    │
│  │  on_action_event(frame: ActionEventFrame):                │    │
│  │    if confidence < CONF_THRESHOLD: return                 │    │
│  │    if stage == "pre" and current_intent == frame.intent:  │    │
│  │      return  (same intent, ignore pre)                    │    │
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
│  ┌─ LipsyncDriver ─────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  AZURE_ID_TO_VISEME: Dict[int, str] = {                  │    │
│  │    0: "sil", 1: "ae_ax_ah", 2: "aa",                     │    │
│  │    3: "ao", 4: "eh_uh", 5: "er",                         │    │
│  │    6: "y_iy_ih_ix", 7: "w_uw", 8: "ow",                 │    │
│  │    9: "aw", 10: "oy", 11: "ay",                          │    │
│  │    12: "h", 13: "r", 14: "l",                            │    │
│  │    15: "s_z", 16: "sh_ch_jh_zh",                         │    │
│  │    17: "th_dh", 18: "f_v", 19: "d_t_n",                  │    │
│  │    20: "k_g_ng", 21: "p_b_m"                             │    │
│  │  }                                                        │    │
│  │                                                           │    │
│  │  on_viseme_event(frame: VisemeEventFrame):                │    │
│  │    viseme_name = AZURE_ID_TO_VISEME[frame.viseme_id]      │    │
│  │    weight = 1.0 if frame.viseme_id != 0 else 0.0          │    │
│  │    → push SetVisemeDriverFrame(                           │    │
│  │        viseme=viseme_name,                                │    │
│  │        weight=weight,                                     │    │
│  │        audio_ts=frame.audio_offset)                       │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─ ModeTracker ────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │  on_frame(frame):                                         │    │
│  │    UserStartedSpeakingFrame → mode=LISTENING              │    │
│  │    UserStoppedSpeakingFrame → mode=THINKING               │    │
│  │    BotStartedSpeakingFrame  → mode=SPEAKING               │    │
│  │    BotStoppedSpeakingFrame  → mode=IDLE                   │    │
│  │    → push SetModeDriverFrame(mode)                        │    │
│  │    → update speaking flag in BaseEmotionSM & MotionCtrl   │    │
│  │                                                           │    │
│  └───────────────────────────────────────────────────────────┘    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

#### Blendshape Conflict Resolution

Controlled entirely by the cloud EmotionModule via `mouth_override` flag:

```
Speaking state (mode=SPEAKING):
  SetEmotionDriverFrame → mouth_override = false
    → Edge applies emotion to eyes, brows, cheeks only
  SetVisemeDriverFrame → always applies to mouth region
    → Edge applies viseme to jaw, lips, tongue

Non-speaking state (mode=IDLE/LISTENING/THINKING):
  SetEmotionDriverFrame → mouth_override = true
    → Edge applies emotion to entire face including mouth
  SetVisemeDriverFrame → not sent (or weight=0)
```

#### Transition Planner Decision Logic

```
Input: current_clip, candidates[], constraints

1. Same intent, different intensity only?
   → PARAM_MORPH { params: {speed, energy, layer_weight} }

2. Different intent, clips are compatible (same body region, smooth blend)?
   → CROSS_FADE { to: best_candidate, fadeMs: 300-500 }

3. Different intent, incompatible clips, bridge animation available?
   → BRIDGE { bridgeClip: matching_bridge, to: target_clip }

4. Different intent, no bridge, must go through safe route?
   → SAFE_ROUTE {
       exit: current_clip.safe_exit,
       idle: "standing_idle",
       entry: target_clip.safe_entry,
       to: target_clip
     }
```

---

### 6.3 AzureVisemeTTSService

**Responsibility**: Extend existing `AzureTTSService` to capture `viseme_received` events.

**Extends**: `AzureTTSService` (which extends `WordTTSService`)

**File**: `src/pipecat/services/azure/tts.py` (extend existing)

#### Key Changes

```python
class AzureVisemeTTSService(AzureTTSService):
    """Azure TTS with Viseme event support for lip sync.

    Extends AzureTTSService to capture viseme_received callbacks
    from the Azure Speech SDK and yield VisemeEventFrame alongside
    audio chunks.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._viseme_queue: asyncio.Queue = asyncio.Queue()

    async def start(self, frame: StartFrame):
        await super().start(frame)
        # Connect viseme callback (in addition to existing callbacks)
        if self._speech_synthesizer:
            self._speech_synthesizer.viseme_received.connect(
                self._handle_viseme_received
            )

    def _handle_viseme_received(self, evt):
        """Handle viseme events from Azure SDK.

        Args:
            evt: VisemeReceivedEventArgs with viseme_id and audio_offset.
        """
        viseme_frame = VisemeEventFrame(
            viseme_id=evt.viseme_id,
            audio_offset=evt.audio_offset / 10_000_000.0,  # ticks → seconds
        )
        self._viseme_queue.put_nowait(viseme_frame)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Override to yield VisemeEventFrame alongside audio."""
        # Clear viseme queue
        while not self._viseme_queue.empty():
            self._viseme_queue.get_nowait()

        async for frame in super().run_tts(text, context_id):
            yield frame
            # After each audio chunk, drain viseme queue
            while not self._viseme_queue.empty():
                yield self._viseme_queue.get_nowait()

    async def _handle_interruption(self, frame, direction):
        await super()._handle_interruption(frame, direction)
        while not self._viseme_queue.empty():
            self._viseme_queue.get_nowait()
```

---

### 6.4 UE Frame Serializer

**Responsibility**: Serialize/deserialize frames for the WebSocket protocol.

**Extends**: `FrameSerializer`

**File**: `src/pipecat/serializers/ue.py`

```python
class UEFrameSerializer(FrameSerializer):
    """Serializer for UE digital human WebSocket protocol.

    Binary frames: audio PCM data
    Text frames: JSON messages (images, control, driver commands)
    """

    async def serialize(self, frame: Frame) -> str | bytes | None:
        # Audio → binary
        if isinstance(frame, AudioRawFrame):
            return frame.audio

        # Transport messages (driver commands, device commands) → JSON
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
        # Binary → audio
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data,
                sample_rate=self._sample_rate,
                num_channels=1,
            )

        # Text → JSON parse
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

### 6.5 Digital Human Output Processor

**Responsibility**: Convert all custom DriverFrame types to `OutputTransportMessageFrame` for WebSocket transport.

**Extends**: `FrameProcessor`

```python
class DigitalHumanOutputProcessor(FrameProcessor):
    """Converts internal DriverFrames to OutputTransportMessageFrame.

    This processor sits between EmotionModule and the transport output.
    It bridges the gap between internal pipeline frame types and
    the WebSocket serialization layer.
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
        SetVisemeDriverFrame: lambda f: {
            "type": "SET_VISEME",
            "viseme": f.viseme,
            "weight": f.weight,
            "audioTs": f.audio_ts,
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

### 6.6 Memory Module

#### MemoryRetriever

**Responsibility**: Before LLM call, retrieve relevant memories and inject into context.

**Extends**: `FrameProcessor`

```
process_frame:
  OpenAILLMContextFrame →
    1. Extract latest user message text
    2. Generate embedding (text-embedding-3-small, async)
    3. Query pgvector: top-K similar memories for this user
       - Filter: user_id, importance > threshold
       - Order: cosine similarity * recency_weight * importance
       - Timeout: 200ms max
    4. Query Redis: hot memory cache (fallback if PG slow)
    5. Inject memories as system message into LLM context:
       "関連する記憶: {memory1}; {memory2}; ..."
    6. Push enriched OpenAILLMContextFrame downstream
```

#### MemoryWriter

**Responsibility**: After LLM response completes, extract and store memories asynchronously.

**Extends**: `FrameProcessor`

```
process_frame:
  LLMFullResponseEndFrame →
    1. Collect completed response text (from aggregation)
    2. Fire async task (non-blocking):
       a. Rule-based extraction: entities, names, dates (regex/NER)
       b. Optional LLM extraction: summarize key facts (lightweight model)
       c. Generate embedding for each extracted fact
       d. Upsert into memories table (deduplicate by similarity)
       e. Update Redis hot cache
       f. Write message to messages table
       g. Increment session turn_count in Redis

  All other frames → pass through immediately (never block pipeline)
```

---

### 6.7 Scene Manager

**Responsibility**: Handle scene/costume state, process edge-initiated and LLM-initiated switches.

**Extends**: `FrameProcessor`

```
process_frame:
  InputTransportMessageFrame →
    if action == "switch_scene":
      1. Load scene config from DB
      2. Update Redis session state
      3. Update LLM context (append scene-specific system prompt)
      4. Push OutputTransportMessageFrame(device_cmd: switch_scene)
      → consume frame (do not propagate)

    if action == "switch_costume":
      1. Validate scene-costume compatibility
      2. Load costume config from DB
      3. Update Redis session state
      4. Push OutputTransportMessageFrame(device_cmd: switch_costume)
      → consume frame (do not propagate)

    else:
      → pass through

  DeviceCommandFrame (from CustomLLM function calls) →
    if action in ["switch_scene", "switch_costume"]:
      Same logic as above, then pass through DeviceCommandFrame
    else:
      → pass through

  All other frames → pass through
```

---

## 7. Database Design

### 7.1 PostgreSQL Schema

```sql
-- ================================================================
-- Extensions
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";        -- pgvector

-- ================================================================
-- Users & Sessions
-- ================================================================

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id       VARCHAR(128) UNIQUE NOT NULL,
    display_name    VARCHAR(64),
    language        VARCHAR(8) DEFAULT 'ja-JP',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    scene_id        UUID REFERENCES scenes(id),
    costume_id      UUID REFERENCES costumes(id),
    started_at      TIMESTAMPTZ DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    summary         TEXT,
    turn_count      INT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_sessions_user ON sessions(user_id, started_at DESC);

-- ================================================================
-- Messages
-- ================================================================

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    emotion         VARCHAR(32),
    has_image       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- ================================================================
-- Long-term Memory (vector retrieval)
-- ================================================================

CREATE TABLE memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category        VARCHAR(32) NOT NULL
                    CHECK (category IN ('fact', 'preference', 'summary', 'event')),
    content         TEXT NOT NULL,
    embedding       vector(1536),          -- text-embedding-3-small dimension
    importance      FLOAT DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    source_session  UUID REFERENCES sessions(id),
    access_count    INT DEFAULT 0,
    last_accessed   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ
);

CREATE INDEX idx_memories_embedding
    ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_memories_user_category
    ON memories(user_id, category);
CREATE INDEX idx_memories_user_importance
    ON memories(user_id, importance DESC);

-- ================================================================
-- Scenes
-- ================================================================

CREATE TABLE scenes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(64) NOT NULL UNIQUE,
    display_name    VARCHAR(128),
    ue_level_name   VARCHAR(128) NOT NULL,
    system_prompt   TEXT,
    default_camera  JSONB,
    ambient_config  JSONB,
    metadata        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,
    sort_order      INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ================================================================
-- Costumes
-- ================================================================

CREATE TABLE costumes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(64) NOT NULL UNIQUE,
    display_name    VARCHAR(128),
    ue_asset_path   VARCHAR(256) NOT NULL,
    morph_target_map JSONB,
    system_prompt   TEXT,                      -- costume-specific persona adjustments
    metadata        JSONB DEFAULT '{}',
    is_active       BOOLEAN DEFAULT true,
    sort_order      INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ================================================================
-- Scene-Costume Compatibility
-- ================================================================

CREATE TABLE scene_costume_rules (
    scene_id        UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    costume_id      UUID NOT NULL REFERENCES costumes(id) ON DELETE CASCADE,
    is_default      BOOLEAN DEFAULT false,
    PRIMARY KEY (scene_id, costume_id)
);
```

### 7.2 Redis Structure

```
# ── Active Session State ──────────────────────────────────

HASH  session:{session_id}
  user_id         : UUID
  scene_id        : UUID
  scene_name      : string
  costume_id      : UUID
  costume_name    : string
  current_emotion : string       # latest emotion from EmotionModule
  current_mode    : string       # IDLE / LISTENING / SPEAKING / THINKING
  turn_count      : int
  recent_topics   : JSON array   # last 5 topics
  pending_facts   : JSON array   # facts buffered for batch write
  TTL: 1800 (30 min inactivity)

# ── User Hot Memory Cache ─────────────────────────────────

ZSET  user_memory:{user_id}:hot
  member: JSON {content, category, importance}
  score:  importance * recency_factor
  Max size: 50 entries
  TTL: 3600 (1 hour, refreshed on session start)

# ── Device Connection Registry ────────────────────────────

HASH  device:{device_id}
  session_id    : UUID
  connected_at  : ISO timestamp
  last_heartbeat: ISO timestamp
  TTL: 60 (heartbeat refresh)
```

---

## 8. Configuration Files

### 8.1 Motion Tree

```yaml
# config/motion_tree.yaml
# Loaded into EmotionModule.MotionController at startup

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

### 8.2 Viseme Mapping

```yaml
# config/viseme_mapping.yaml
# Azure Viseme ID → viseme name + default morph target weights

azure_viseme_map:
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

# Japanese-specific adjustments (override defaults)
japanese_overrides:
  # Japanese vowels: あ(a) い(i) う(u) え(e) お(o)
  # Map to closest Azure visemes for Japanese phonology
  2:  {name: "aa",  jaw: 0.55, mouth_open: 0.65, lips_round: 0.00}   # あ
  6:  {name: "ii",  jaw: 0.10, mouth_open: 0.10, lips_round: 0.00}   # い
  7:  {name: "uu",  jaw: 0.15, mouth_open: 0.10, lips_round: 0.65}   # う
  4:  {name: "ee",  jaw: 0.25, mouth_open: 0.30, lips_round: 0.00}   # え
  3:  {name: "oo",  jaw: 0.40, mouth_open: 0.40, lips_round: 0.50}   # お
```

### 8.3 Emotion Configuration

```yaml
# config/emotion_config.yaml

base_emotion:
  confidence_threshold: 0.6
  decay_timeout_s: 5.0
  default_fade_ms: 300

  # Fade duration between specific emotion pairs
  transition_overrides:
    neutral_to_happy: 250
    neutral_to_sad: 400
    happy_to_sad: 500
    angry_to_neutral: 400
    surprised_to_neutral: 200

  # Emotion → non-mouth blendshape defaults
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

## 9. Edge Architecture (RK3588 + UE5)

### 9.1 UE Application Structure

```
UE5 Application (Android, RK3588)
│
├─ WebSocketClient (C++ or Blueprint)
│   ├─ Connect to wss://cloud-server/ws/digital-human
│   ├─ Send: audio PCM (binary), image JPEG (text), control (text)
│   └─ Receive: audio PCM (binary), driver commands (text)
│
├─ MessageRouter
│   ├─ Binary frames → AudioPlaybackManager
│   └─ Text frames → JSON parse → CommandDispatcher
│
├─ CommandDispatcher
│   ├─ SET_EMOTION  → EmotionApplicator
│   ├─ SET_VISEME   → VisemeApplicator
│   ├─ PLAY_MOTION  → MotionExecutor
│   ├─ SET_MODE     → ModeController
│   ├─ SET_GAZE     → GazeController
│   ├─ device_cmd   → DeviceCommandHandler
│   └─ text         → SubtitleDisplay
│
├─ AudioPlaybackManager
│   ├─ PCM buffer queue
│   ├─ UAudioComponent playback
│   └─ Timestamp tracking (t0 for viseme sync)
│
├─ EmotionApplicator
│   ├─ Target blendshape weights (from emotion presets)
│   ├─ Smooth interpolation (fadeMs)
│   ├─ Region mask: if !mouthOverride → skip mouth blendshapes
│   └─ Apply to SkeletalMeshComponent
│
├─ VisemeApplicator
│   ├─ Viseme → morph target weight lookup
│   ├─ Schedule by audioTs relative to audio t0
│   ├─ Smooth interpolation between visemes
│   ├─ Priority: always overrides mouth region when active
│   └─ Apply to SkeletalMeshComponent
│
├─ MotionExecutor
│   ├─ Parse MotionPlan
│   ├─ CROSS_FADE  → UAnimInstance.Montage_Play with blend
│   ├─ PARAM_MORPH → adjust anim parameters (speed, weight)
│   ├─ BRIDGE      → play bridge clip → then target clip
│   ├─ SAFE_ROUTE  → exit → idle → entry → target (sequenced)
│   └─ Animation Blueprint integration
│
├─ ModeController
│   ├─ IDLE      → idle animation set, eye blink, breathing
│   ├─ LISTENING → attentive pose, slight lean forward
│   ├─ THINKING  → thinking animation, look away
│   └─ SPEAKING  → base speaking pose, enable viseme
│
├─ GazeController
│   ├─ IK-based head/eye tracking
│   └─ target: "user" → camera direction, "away" → random offset
│
├─ DeviceCommandHandler
│   ├─ capture_camera  → Camera2 API → JPEG → upload
│   ├─ switch_scene    → Level streaming / sublevel load
│   ├─ switch_costume  → Skeletal mesh / material swap
│   ├─ play_effect     → Niagara particle system
│   └─ show_ui         → UMG widget visibility
│
└─ Digital Human Character (Blueprint)
    ├─ SkeletalMeshComponent (custom model)
    │   ├─ Morph Targets (mouth, face, body)
    │   └─ Materials (per-costume)
    ├─ Animation Blueprint
    │   ├─ Montage slots (upper body, full body)
    │   ├─ Blend spaces
    │   └─ IK chains (gaze, hands)
    └─ Audio Component
```

### 9.2 Blendshape Application Priority (UE Tick)

```cpp
void ADigitalHuman::ApplyBlendshapes(float DeltaTime)
{
    // 1. Apply emotion to all blendshapes
    for (auto& [Name, Weight] : EmotionApplicator->GetCurrentWeights())
    {
        if (VisemeApplicator->IsActive() && !EmotionApplicator->MouthOverride())
        {
            // During speech: skip mouth-region blendshapes
            if (IsMouthRegion(Name)) continue;
        }
        Mesh->SetMorphTarget(Name, Weight);
    }

    // 2. Apply viseme to mouth blendshapes (overrides emotion for mouth)
    if (VisemeApplicator->IsActive())
    {
        for (auto& [Name, Weight] : VisemeApplicator->GetCurrentWeights())
        {
            Mesh->SetMorphTarget(Name, Weight);
        }
    }
}
```

---

## 10. Time Synchronization

### 10.1 Audio-Viseme Sync (per-utterance relative time)

```
Cloud:
  TTS starts utterance → audioTs base = 0.0
  VisemeEventFrame.audio_offset = seconds from utterance start
  TTSAudioRawFrame = PCM chunks sequentially

Edge:
  First audio chunk received → record t0 = system_clock
  SET_VISEME.audioTs = offset from t0
  Schedule: apply viseme at t0 + audioTs

  Jitter buffer: hold 2-3 audio chunks (~40-60ms) before playback
  Viseme commands pre-buffered and applied at scheduled time
```

### 10.2 Emotion/Action Timing (fire-and-forget)

Emotion and action commands use `fadeMs` for smooth transitions. Exact timing is not critical — the fade handles any network jitter. The `ts` field is monotonic for ordering only.

### 10.3 Network Latency Handling

```
Uplink latency (audio):   50-100ms typical
Downlink latency (audio): 50-100ms typical
Downlink latency (JSON):  50-100ms typical

Strategy:
  - Audio: jitter buffer on edge (60ms)
  - Viseme: pre-buffered, scheduled by audioTs
  - Emotion/Action: fade-based, tolerant to jitter
  - Mode changes: immediate apply, no scheduling needed
```

---

## 11. Error Handling & Reconnection

### 11.1 WebSocket Reconnection (Edge)

```
Connection lost:
  1. UE detects WebSocket close/error
  2. Character enters "offline" idle animation
  3. Exponential backoff reconnection: 1s, 2s, 4s, 8s, max 30s
  4. On reconnect:
     a. Send device_id for session recovery
     b. Cloud checks Redis for active session
     c. If session exists: resume (restore scene/costume state)
     d. If session expired: create new session
```

### 11.2 Cloud Pipeline Errors

```
STT error:    push ErrorFrame(fatal=false), retry with next audio chunk
LLM error:    push ErrorFrame(fatal=false), send apology message via TTS
TTS error:    push ErrorFrame(fatal=false), try fallback voice
Memory error: log, continue without memory (graceful degradation)
Fatal error:  push ErrorFrame(fatal=true), send EndFrame, close connection
```

### 11.3 Edge Device Errors

```
Camera capture failed: send device_response(status="error")
Scene load failed:     send device_response(status="error"), stay in current scene
Audio playback error:  attempt recovery, log to cloud via control message
```

---

## 12. Latency Budget

```
┌─────────────────────────────────────────────────────────┐
│ End-to-end: user stops speaking → first audio playback  │
│ Target: < 1.5s                                          │
├──────────────────────────────┬──────────────────────────┤
│ Segment                      │ Budget                   │
├──────────────────────────────┼──────────────────────────┤
│ Audio uplink (network)       │ 50-100ms                 │
│ VAD tail (speech end detect) │ 200-400ms                │
│ STT final result             │ 100-200ms (streaming)    │
│ Memory retrieval             │ < 200ms (with timeout)   │
│ LLM first token              │ 200-500ms                │
│ Sentence aggregation (日語)  │ 50-100ms (。！？ split)  │
│ TTS first audio chunk        │ 100-200ms                │
│ Audio downlink (network)     │ 50-100ms                 │
│ Edge jitter buffer           │ 60ms                     │
├──────────────────────────────┼──────────────────────────┤
│ Total                        │ ~800-1500ms              │
├──────────────────────────────┴──────────────────────────┤
│ Emotion pre-event can fire during LLM streaming,        │
│ reaching edge 200-500ms before audio, enabling           │
│ anticipatory expression changes.                         │
└─────────────────────────────────────────────────────────┘
```

---

## 13. File Structure

```
src/pipecat/
├── frames/
│   ├── frames.py                      # Existing frame definitions
│   └── digital_human.py              # NEW: All custom frame types (§5.2)
│
├── services/
│   └── azure/
│       ├── tts.py                     # Existing (+ AzureVisemeTTSService §6.3)
│       ├── stt.py                     # Existing
│       └── common.py                  # Existing
│
├── serializers/
│   ├── base_serializer.py             # Existing
│   └── ue.py                          # NEW: UEFrameSerializer (§6.4)
│
├── processors/
│   └── digital_human/
│       ├── __init__.py
│       ├── custom_llm.py             # NEW: CustomLLMProcessor (§6.1)
│       ├── emotion_module.py         # NEW: EmotionModule (§6.2)
│       ├── output_processor.py       # NEW: DigitalHumanOutputProcessor (§6.5)
│       ├── memory_retriever.py       # NEW: MemoryRetriever (§6.6)
│       ├── memory_writer.py          # NEW: MemoryWriter (§6.6)
│       └── scene_manager.py          # NEW: SceneManager (§6.7)
│
├── transports/
│   └── websocket/
│       └── server.py                  # Existing (used as-is)
│
└── pipeline/
    ├── pipeline.py                    # Existing
    ├── task.py                        # Existing
    └── runner.py                      # Existing

config/
├── motion_tree.yaml                   # Motion tree definition (§8.1)
├── viseme_mapping.yaml                # Viseme mapping (§8.2)
└── emotion_config.yaml                # Emotion state machine config (§8.3)

db/
└── migrations/
    └── 001_initial_schema.sql         # PostgreSQL schema (§7.1)

examples/
└── digital_human/
    └── server.py                      # Cloud server entry point (§4.3)

tests/
└── test_digital_human/
    ├── test_emotion_module.py
    ├── test_custom_llm.py
    ├── test_ue_serializer.py
    └── test_output_processor.py
```

---

## 14. Implementation Priority

| Phase | Modules | Milestone |
|-------|---------|-----------|
| **P0** | UESerializer + WebSocket transport + basic audio round-trip | Edge ↔ Cloud audio works |
| **P1** | FishAudioTTS + Edge AudioDrivenLipsync | TTS audio + edge lip sync works |
| **P2** | CustomLLM (Gemini 3.0 Flash, basic) + STT + context aggregation | Voice conversation works |
| **P3** | EmotionEventFrame + BaseEmotionSM + SetEmotionDriverFrame | Facial expressions work |
| **P4** | ActionEventFrame + MotionController + TransitionPlanner | Body motion works |
| **P5** | MemoryRetriever + MemoryWriterObserver + DB schema | Cross-session memory works |
| **P6** | Scene/costume function calls + PromptManager scene injection | Scene/costume system works |
| **P7** | EventStabilizer (pre/final) + debounce + confidence tuning | Production quality polish |
