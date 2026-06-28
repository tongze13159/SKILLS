from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelInfo(StrictModel):
    provider: str
    model: str
    temperature: Optional[float] = None


class ArtifactHeader(StrictModel):
    schema_version: str = "1.0.0"
    project_id: str
    artifact_id: str
    created_at: datetime
    source_artifacts: List[str] = Field(default_factory=list)
    model_info: ModelInfo
    cost_rmb: float = Field(default=0.0, ge=0)


class AdapterResult(StrictModel):
    ok: bool
    artifact_path: Optional[str] = None
    raw_response_path: Optional[str] = None
    cost_rmb: float = Field(default=0.0, ge=0)
    error: Optional[str] = None
    retryable: bool = False


class VideoMeta(StrictModel):
    duration_ms: int = Field(gt=0)
    aspect_ratio: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    has_audio: bool


class RawShot(StrictModel):
    reference_shot_id: str = Field(pattern=r"^ref_\d{3}$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    keyframes: Dict[str, str]
    motion_peak_frames: List[str]
    motion_intensity: Literal["low", "medium", "high"]


class RawShotsArtifact(ArtifactHeader):
    video_meta: VideoMeta
    raw_shots: List[RawShot]


class SubtitleGroup(StrictModel):
    subtitle_group_id: str = Field(pattern=r"^sub_\d{3}$")
    reference_shot_ids: List[str]
    text: str
    position: str
    confidence: float = Field(ge=0, le=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    needs_review: bool


class OcrSubtitlesArtifact(ArtifactHeader):
    subtitle_groups: List[SubtitleGroup]


class VoiceSegment(StrictModel):
    voice_segment_id: str = Field(pattern=r"^v_\d{3}$")
    reference_shot_ids: List[str]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str
    language: str
    confidence: float = Field(ge=0, le=1)


class VoiceTranscriptArtifact(ArtifactHeader):
    voice_segments: List[VoiceSegment]


class ReferenceVisualAnalysisArtifact(ArtifactHeader):
    reference_shots: List[Dict[str, Any]]


class ReferenceShotStrategyArtifact(ArtifactHeader):
    reference_shots: List[Dict[str, Any]]
    overall_structure: Dict[str, List[int]]


class ProductProfileArtifact(ArtifactHeader):
    product_profile: Dict[str, Any]


class ProductAction(StrictModel):
    action_id: str = Field(pattern=r"^act_\d{3}(?:_fallback)?$")
    action_name: str
    difficulty: Literal["low", "medium", "high"]
    video_generation_risk: Literal["low", "medium", "high"]
    visual_clarity: Literal["low", "medium", "high"]
    suitable_shot_functions: List[str]
    required_props: List[str]
    best_camera: Dict[str, str]
    start_state: str
    main_motion: str
    end_state: str
    avoid: List[str]
    fallback_action_id: Optional[str] = None


class ProductActionMatrixArtifact(ArtifactHeader):
    product_action_matrix: List[ProductAction]


class ActionTransferPlanArtifact(ArtifactHeader):
    action_transfer_plan: List[Dict[str, Any]]


class Camera(StrictModel):
    angle: str
    distance: str
    movement: str


class Scene(StrictModel):
    type: str
    background: str


class NewShot(StrictModel):
    new_shot_id: str = Field(pattern=r"^new_\d{3}$")
    reference_shot_id: str = Field(pattern=r"^ref_\d{3}$")
    duration_ms: int = Field(gt=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    shot_function: Literal[
        "hook",
        "pain_point",
        "product_reveal",
        "function_demo",
        "proof",
        "comparison",
        "scenario",
        "transition",
        "cta",
    ]
    commercial_purpose: str
    selected_action_id: str
    visual_action: str
    camera: Camera
    scene: Scene
    product_focus: List[str] = Field(min_length=1)
    subtitle_intent: str
    voiceover_intent: str
    must_keep_from_reference: List[str]
    must_change_from_reference: List[str]
    generation_risks: List[str] = Field(min_length=1)
    source_new_shot_ids: List[str] = Field(min_length=1)
    source_reference_shot_ids: List[str] = Field(min_length=1)
    generation_strategy: Literal["standalone", "adjacent_merge", "shot_split"]


class NewVideoPlanBody(StrictModel):
    project_id: str
    duration_ms: int = Field(gt=0)
    shot_count: int = Field(gt=0)
    target_language: str
    voice_gender: str
    source_reference_shot_count: int | None = Field(default=None, gt=0)
    shots: List[NewShot]


class NewVideoPlanArtifact(ArtifactHeader):
    new_video_plan: NewVideoPlanBody


class SubtitleScriptArtifact(ArtifactHeader):
    subtitle_script: List[Dict[str, Any]]


class VoiceoverScriptArtifact(ArtifactHeader):
    voiceover_script: List[Dict[str, Any]]


class AudioAssetManifestArtifact(ArtifactHeader):
    bgm: Dict[str, Any]
    sfx_events: List[Dict[str, Any]]


class StoryboardPrompt(StrictModel):
    new_shot_id: str = Field(pattern=r"^new_\d{3}$")
    image_model: str
    prompt: str
    negative_prompt: str
    reference_image_ids: List[str]
    aspect_ratio: str
    resolution: str
    action_start_state: str
    purpose: Literal["first_frame_for_seedance"]


class StoryboardPromptsArtifact(ArtifactHeader):
    storyboard_prompts: List[StoryboardPrompt]


class Storyboard(StrictModel):
    new_shot_id: str
    image_id: str
    image_path: str
    model: str
    source_prompt_id: str
    selected: bool


class StoryboardManifestArtifact(ArtifactHeader):
    storyboards: List[Storyboard]


class StoryboardPrecheckArtifact(ArtifactHeader):
    storyboard_precheck: List[Dict[str, Any]]


class SeedanceTask(StrictModel):
    task_id: str
    project_id: str
    new_shot_id: str
    reference_shot_id: str
    product_id: str
    action_id: str
    duration_ms: int = Field(gt=0)
    resolution: str
    aspect_ratio: str
    fps: int = Field(gt=0)
    input_image: str
    input_images: List[str] = Field(min_length=1)
    prompt: str
    negative_prompt: str
    camera: Camera
    motion: Dict[str, str]
    product_consistency_rules: List[str] = Field(min_length=1)
    difference_rules: List[str] = Field(min_length=1)
    seedance_duration_sec: int = Field(ge=4, le=15)
    merge_strategy: Literal["standalone", "adjacent_merge", "shot_split"]
    source_new_shot_ids: List[str] = Field(min_length=1)
    source_reference_shot_ids: List[str] = Field(min_length=1)
    source_action_ids: List[str] = Field(min_length=1)
    source_segments: List[Dict[str, Any]] = Field(min_length=1)
    fallback: Dict[str, Any]
    estimated_cost_rmb: float = Field(ge=0)


class SeedanceTasksArtifact(ArtifactHeader):
    seedance_tasks: List[SeedanceTask]
    estimated_total_cost_rmb: float = Field(ge=0)
    budget_rmb: float = Field(ge=0)
    budget_status: Literal["ok", "warning", "blocked"]


class VideoClipsManifestArtifact(ArtifactHeader):
    video_clips: List[Dict[str, Any]]


class RenderPlanArtifact(ArtifactHeader):
    render_plan: Dict[str, Any]


class PipelineStateArtifact(ArtifactHeader):
    status: Literal["pending", "running", "completed", "failed", "blocked"]
    dry_run: bool
    current_step: Optional[str] = None
    steps: Dict[str, Dict[str, Any]]
    total_cost_rmb: float = Field(ge=0)
    max_budget_rmb: float = Field(ge=0)
    error: Optional[str] = None


class CostLedgerArtifact(ArtifactHeader):
    budget_rmb: float = Field(ge=0)
    warn_budget_rmb: float = Field(ge=0)
    spent_rmb: float = Field(ge=0)
    estimated_rmb: float = Field(ge=0)
    items: List[Dict[str, Any]]


class InputManifestArtifact(ArtifactHeader):
    inputs: Dict[str, Any]


class VoiceoverAssetManifestArtifact(ArtifactHeader):
    voiceover: Dict[str, Any]
    segments: List[Dict[str, Any]]


class FinalVideoManifestArtifact(ArtifactHeader):
    final_video: Dict[str, Any]


SCHEMA_MODELS = {
    "input_manifest.schema.json": InputManifestArtifact,
    "raw_shots.schema.json": RawShotsArtifact,
    "ocr_subtitles.schema.json": OcrSubtitlesArtifact,
    "voice_transcript.schema.json": VoiceTranscriptArtifact,
    "reference_visual_analysis.schema.json": ReferenceVisualAnalysisArtifact,
    "reference_shot_strategy.schema.json": ReferenceShotStrategyArtifact,
    "product_profile.schema.json": ProductProfileArtifact,
    "product_action_matrix.schema.json": ProductActionMatrixArtifact,
    "action_transfer_plan.schema.json": ActionTransferPlanArtifact,
    "new_video_plan.schema.json": NewVideoPlanArtifact,
    "subtitle_script.schema.json": SubtitleScriptArtifact,
    "voiceover_script.schema.json": VoiceoverScriptArtifact,
    "audio_asset_manifest.schema.json": AudioAssetManifestArtifact,
    "storyboard_prompts.schema.json": StoryboardPromptsArtifact,
    "storyboard_manifest.schema.json": StoryboardManifestArtifact,
    "storyboard_precheck.schema.json": StoryboardPrecheckArtifact,
    "seedance_tasks.schema.json": SeedanceTasksArtifact,
    "video_clips_manifest.schema.json": VideoClipsManifestArtifact,
    "render_plan.schema.json": RenderPlanArtifact,
    "pipeline_state.schema.json": PipelineStateArtifact,
    "cost_ledger.schema.json": CostLedgerArtifact,
    "voiceover_asset_manifest.schema.json": VoiceoverAssetManifestArtifact,
    "final_video_manifest.schema.json": FinalVideoManifestArtifact,
}
