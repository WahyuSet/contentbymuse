from app.domain.llm_outputs import ScriptDraft, ValidationOutput

_NO_MASCOT_TAG = "[NO_MASCOT]"


def count_words(text: str) -> int:
    return len(text.split())


def estimate_scene_s(voiceover: str, wps: float) -> float:
    return count_words(voiceover) / wps + 0.15


def validate_script_draft(draft: ScriptDraft) -> ScriptDraft:
    """Aturan bisnis ScriptDraft (Spec §3.2). Melempar ValueError berpesan spesifik."""
    n = len(draft.scenes)
    if not 8 <= n <= 14:
        raise ValueError(f"Jumlah scene wajib 8 sampai 14, diterima {n}.")
    for position, scene in enumerate(draft.scenes, start=1):
        words = count_words(scene.voiceover)
        if not 3 <= words <= 16:
            raise ValueError(
                f"Scene {position}: voiceover wajib 3 sampai 16 kata, sekarang {words} kata."
            )
        prompt = scene.visual_prompt.lstrip()
        if prompt.upper().startswith(_NO_MASCOT_TAG):
            scene.visual_prompt = prompt[len(_NO_MASCOT_TAG) :].lstrip()
            scene.include_mascot = False
    if draft.scenes:
        # Hook selalu narasi scene 1 (§3.2); disalin kode, bukan dipercaya dari LLM.
        draft.hook = draft.scenes[0].voiceover
    return draft


def apply_validation_rules(output: ValidationOutput) -> ValidationOutput:
    """Aturan bisnis ValidationOutput (Spec §3.3): PASS tidak boleh membawa error."""
    if output.status == "PASS" and any(
        issue.severity == "error" for issue in output.issues
    ):
        output.status = "NEEDS_REVISION"
    return output
