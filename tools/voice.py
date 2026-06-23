"""
INTI - TAS (AI Agent Version) — Voice Tool (Bidirectional TTS + STT)
=================================================
Gives KRONOS a voice AND ears using lightweight, local models.

TTS (Output — speak):
  Primary:   Kokoro 82M (~500MB VRAM, speaks Spanish + 9 languages)
  Optional:  Chatterbox-Turbo 350M (~2GB VRAM, voice cloning)

STT (Input — listen):
  Primary:   Moonshine v2 (27M params, ~8MB RAM, CPU-only, Spanish support)
  Runs 100% on CPU — does NOT touch GPU VRAM.

The voice cloning and STT engines are lazy-loaded only when requested.

Actions:
  speak       — Generate speech audio from text (Kokoro TTS)
  listen      — Record from microphone and transcribe to text (Moonshine STT)
  clone_speak — Generate speech using a cloned voice (Chatterbox, optional)
  list_voices — List available voices for the current language
  set_voice   — Change the active voice
  set_lang    — Change the active language

Risk: LOW — generates audio files, no system modification.

Install:
  pip install kokoro kokoro-onnx soundfile   (for Kokoro TTS)
  pip install moonshine-voice                 (for Moonshine STT)
  pip install chatterbox-tts                  (optional, for voice cloning)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Output directory for generated audio
_AUDIO_DIR = Path(__file__).resolve().parent.parent / "data" / "audio"

# Language code mapping for Kokoro
KOKORO_LANGUAGES = {
    "en": "a",      # American English
    "en-gb": "b",   # British English
    "es": "e",      # Spanish
    "fr": "f",      # French
    "hi": "h",      # Hindi
    "it": "i",      # Italian
    "ja": "j",      # Japanese
    "ko": "k",      # Korean
    "pt-br": "p",   # Brazilian Portuguese
    "zh": "z",      # Mandarin Chinese
}

# Default voices per language (Kokoro naming convention: {lang_code}{f/m}_{name})
DEFAULT_VOICES = {
    "en": "af_heart",         # American English female
    "en-gb": "bf_emma",       # British English female
    "es": "ef_dora",          # Spanish female
    "fr": "ff_siwis",         # French female
    "ja": "jf_alpha",         # Japanese female
    "ko": "kf_yunju",         # Korean female
    "zh": "zf_xiaobei",       # Chinese female
    "hi": "hf_alpha",         # Hindi female
    "it": "if_sara",          # Italian female
    "pt-br": "pf_dora",       # Portuguese female
}


class VoiceTool(Tool):
    """
    Bidirectional voice for KRONOS: TTS (speak) + STT (listen).

    TTS: Kokoro 82M (~500MB VRAM, multilingual)
    STT: Moonshine v2 (27M params, CPU-only, ~8MB RAM, Spanish native)
    Optional: Chatterbox-Turbo (voice cloning, ~2GB VRAM, lazy-loaded)
    """

    name = "voice"
    description = (
        "Bidirectional voice: speak (TTS) and listen (STT). "
        "Supports Spanish, English, French, Japanese, Korean, Chinese, "
        "Hindi, Italian, Portuguese. "
        "Actions: speak (text→audio), listen (mic/file→text), "
        "clone_speak (voice cloning), list_voices, set_voice, set_lang. "
        "TTS audio saved to data/audio/. STT runs on CPU only."
    )
    category = ToolCategory.UTILITY
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("action", "One of: speak, listen, clone_speak, list_voices, set_voice, set_lang", "string", True),
        ToolParam("text", "Text to convert to speech (speak/clone_speak)", "string", False),
        ToolParam("lang", "Language code: en, es, fr, ja, ko, zh, hi, it, pt-br, en-gb", "string", False, "es"),
        ToolParam("voice", "Voice name (see list_voices)", "string", False),
        ToolParam("speed", "Speech speed multiplier (0.5-2.0, default 1.0)", "float", False, 1.0),
        ToolParam("reference_audio", "Path to reference audio for voice cloning (clone_speak only)", "string", False),
        ToolParam("filename", "Optional output filename (without extension)", "string", False),
        ToolParam("audio_file", "Path to audio file to transcribe (listen action, optional — uses mic if not provided)", "string", False),
        ToolParam("duration", "Recording duration in seconds for mic listen (default: 5)", "float", False, 5.0),
    ]

    def __init__(self):
        self._kokoro_pipeline = None
        self._chatterbox_model = None
        self._moonshine_transcriber = None
        self._moonshine_model_path = None
        self._current_lang = "es"
        self._current_voice = DEFAULT_VOICES.get("es", "ef_dora")

    # ----------------------------------------------------------------
    # Main execute dispatcher
    # ----------------------------------------------------------------

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if not action:
            return ToolResult(success=False, error="Missing 'action' parameter")

        try:
            if action == "speak":
                return await self._speak(kwargs)
            elif action == "listen":
                return await self._listen(kwargs)
            elif action == "conversation":
                return await self._conversation(kwargs)
            elif action == "clone_speak":
                return await self._clone_speak(kwargs)
            elif action == "list_voices":
                return await self._list_voices(kwargs)
            elif action == "set_voice":
                return await self._set_voice(kwargs)
            elif action == "set_lang":
                return await self._set_lang(kwargs)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. Use: speak, listen, conversation, clone_speak, list_voices, set_voice, set_lang",
                )
        except ImportError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[VOICE] Error: {e}")
            return ToolResult(success=False, error=str(e))

    # ----------------------------------------------------------------
    # Action: speak — Kokoro TTS (primary, lightweight)
    # ----------------------------------------------------------------

    async def _speak(self, kwargs: dict) -> ToolResult:
        """Generate speech using Kokoro 82M."""
        text = kwargs.get("text", "").strip()
        if not text:
            return ToolResult(success=False, error="Missing 'text' parameter")

        lang = kwargs.get("lang", self._current_lang)
        voice = kwargs.get("voice", self._current_voice)
        speed = max(0.5, min(2.0, kwargs.get("speed", 1.0)))

        # Lazy-load Kokoro pipeline
        if self._kokoro_pipeline is None:
            try:
                from kokoro import KPipeline
                lang_code = KOKORO_LANGUAGES.get(lang, "e")
                self._kokoro_pipeline = KPipeline(lang_code=lang_code)
                logger.info(f"[VOICE] Kokoro pipeline loaded (lang={lang})")
            except ImportError:
                return ToolResult(
                    success=False,
                    error="kokoro is not installed. Run: pip install kokoro soundfile",
                )

        # Ensure output directory exists
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)

        # Generate audio
        start = time.time()
        try:
            import soundfile as sf

            # Kokoro generates audio segments
            generator = self._kokoro_pipeline(
                text, voice=voice, speed=speed
            )

            # Collect all audio segments
            all_audio = []
            sample_rate = 24000  # Kokoro default
            for _gs, _ps, audio_segment in generator:
                all_audio.append(audio_segment)

            if not all_audio:
                return ToolResult(
                    success=False,
                    error="No audio generated — text may be too short or unsupported",
                )

            # Concatenate segments
            import numpy as np
            full_audio = np.concatenate(all_audio)

            # Save to file
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = kwargs.get("filename", f"kronos_{timestamp}")
            filepath = _AUDIO_DIR / f"{filename}.wav"
            sf.write(str(filepath), full_audio, sample_rate)

            elapsed = (time.time() - start) * 1000
            duration_s = len(full_audio) / sample_rate

            # Auto-play through speakers
            played = False
            try:
                import sounddevice as sd
                sd.play(full_audio, samplerate=sample_rate)
                sd.wait()  # Block until playback finishes
                played = True
                logger.info(f"[VOICE] Auto-played {duration_s:.1f}s of audio")
            except Exception as play_err:
                logger.warning(f"[VOICE] Auto-play failed (file saved OK): {play_err}")

            return ToolResult(
                success=True,
                output={
                    "path": str(filepath),
                    "duration_seconds": round(duration_s, 2),
                    "sample_rate": sample_rate,
                    "voice": voice,
                    "language": lang,
                    "text_length": len(text),
                    "auto_played": played,
                },
                metadata={
                    "path": str(filepath),
                    "elapsed_ms": round(elapsed, 0),
                    "engine": "kokoro-82m",
                    "speed": speed,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Kokoro generation error: {e}")

    # ----------------------------------------------------------------
    # Action: listen — Moonshine v2 STT (CPU-only, Spanish native)
    # ----------------------------------------------------------------

    def _init_moonshine(self, lang: str = None):
        """
        Lazy-initialize Moonshine v2 transcriber.
        Downloads language-specific model on first run (~60MB), then cached.
        Runs entirely on CPU — does NOT touch GPU VRAM.

        Correct API:
          get_model_for_language('es') → (model_path_str, ModelArch)
          Transcriber(model_path=str, model_arch=ModelArch)
        """
        target_lang = lang or self._current_lang

        # Map KRONOS language codes to Moonshine codes
        lang_map = {
            "en": "en", "en-gb": "en", "es": "es", "ja": "ja",
            "ko": "ko", "zh": "zh", "ar": "ar", "vi": "vi", "uk": "uk",
        }
        ms_lang = lang_map.get(target_lang, "en")

        # If already initialized for same language, skip
        if (
            self._moonshine_transcriber is not None
            and self._moonshine_model_path == ms_lang
        ):
            return True

        try:
            from moonshine_voice import (
                get_model_for_language,
                get_model_path,
                ModelArch,
            )
            from moonshine_voice.transcriber import Transcriber

            # Get language-specific model (downloads on first call)
            model_path_str, model_arch = get_model_for_language(ms_lang)

            # Resolve the model path
            resolved_path = get_model_path(model_path_str)

            # Create transcriber with correct API
            self._moonshine_transcriber = Transcriber(
                model_path=str(resolved_path),
                model_arch=model_arch,
            )
            self._moonshine_model_path = ms_lang
            logger.info(
                f"[VOICE] Moonshine STT initialized "
                f"(lang={ms_lang}, arch={model_arch}, CPU-only)"
            )
            return True

        except ImportError:
            logger.error(
                "[VOICE] Moonshine not installed. "
                "Run: pip install moonshine-voice"
            )
            return False
        except Exception as e:
            logger.error(f"[VOICE] Moonshine init failed: {e}")
            return False

    def _record_mic(self, duration: float = 5.0, sample_rate: int = 16000) -> "numpy.ndarray":
        """Record audio from microphone for a given duration."""
        import numpy as np

        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError(
                "sounddevice is not installed. Run: pip install sounddevice"
            )

        logger.info(f"[VOICE] Recording {duration}s from microphone...")
        audio = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype='float32',
        )
        sd.wait()  # Block until recording is done
        logger.info("[VOICE] Recording complete.")
        return audio.flatten()

    async def _listen(self, kwargs: dict) -> ToolResult:
        """
        Record from microphone or load audio file, then transcribe.

        If 'audio_file' is provided, transcribe that file.
        Otherwise, record from the default microphone for 'duration' seconds.
        """
        audio_file = kwargs.get("audio_file", "")
        duration = max(1.0, min(30.0, kwargs.get("duration", 5.0)))
        lang = kwargs.get("lang", self._current_lang)

        # Initialize Moonshine STT for the requested language
        if not self._init_moonshine(lang=lang):
            return ToolResult(
                success=False,
                error="Moonshine STT not available. Install: pip install moonshine-voice",
            )

        start = time.time()

        try:
            import numpy as np

            if audio_file:
                # Load from file
                audio_path = Path(audio_file)
                if not audio_path.exists():
                    return ToolResult(
                        success=False,
                        error=f"Audio file not found: {audio_file}",
                    )

                try:
                    import soundfile as sf
                    audio, sr = sf.read(str(audio_path))
                    # Convert to mono if stereo
                    if len(audio.shape) > 1:
                        audio = audio.mean(axis=1)
                    # Resample to 16kHz if needed
                    if sr != 16000:
                        import scipy.signal
                        audio = scipy.signal.resample(
                            audio, int(len(audio) * 16000 / sr)
                        )
                    audio = audio.astype(np.float32)
                except ImportError:
                    return ToolResult(
                        success=False,
                        error="soundfile not installed. Run: pip install soundfile",
                    )
                source = f"file:{audio_path.name}"
            else:
                # Record from microphone
                audio = self._record_mic(duration=duration, sample_rate=16000)
                source = f"mic:{duration}s"

            # Transcribe with Moonshine
            try:
                transcriber = self._moonshine_transcriber

                # Prefer batch transcription if available
                if hasattr(transcriber, 'transcribe_without_streaming'):
                    result = transcriber.transcribe_without_streaming(
                        audio.tolist(), 16000
                    )
                    if hasattr(result, 'lines'):
                        text = " ".join(line.text for line in result.lines if line.text)
                    elif isinstance(result, str):
                        text = result
                    else:
                        text = str(result)

                else:
                    # Event-based streaming transcription
                    from moonshine_voice.transcriber import TranscriptEventListener

                    transcript_text = []

                    class _Listener(TranscriptEventListener):
                        def on_line_completed(self, event):
                            if event.line and event.line.text:
                                transcript_text.append(event.line.text)

                        def on_line_started(self, event):
                            pass

                        def on_line_text_changed(self, event):
                            pass

                    listener = _Listener()
                    transcriber.add_listener(listener)
                    transcriber.start()

                    # Feed audio in 100ms chunks as List[float]
                    chunk_size = int(0.1 * 16000)  # 1600 samples
                    for i in range(0, len(audio), chunk_size):
                        chunk = audio[i:i + chunk_size]
                        transcriber.add_audio(chunk.tolist(), 16000)

                    transcriber.stop()
                    transcriber.remove_listener(listener)
                    text = " ".join(transcript_text)

            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"Moonshine transcription error: {e}",
                )

            elapsed = (time.time() - start) * 1000
            text = text.strip()

            if not text:
                return ToolResult(
                    success=True,
                    output={
                        "text": "",
                        "message": "No speech detected in audio",
                        "source": source,
                    },
                    metadata={
                        "elapsed_ms": round(elapsed, 0),
                        "engine": "moonshine-v2",
                        "language": lang,
                    },
                )

            return ToolResult(
                success=True,
                output={
                    "text": text,
                    "source": source,
                    "word_count": len(text.split()),
                    "language": lang,
                },
                metadata={
                    "elapsed_ms": round(elapsed, 0),
                    "engine": "moonshine-v2",
                    "chars": len(text),
                },
            )

        except ImportError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"STT error: {e}")

    # ----------------------------------------------------------------
    # Action: conversation — speak then listen (bidirectional voice)
    # ----------------------------------------------------------------

    async def _conversation(self, kwargs: dict) -> ToolResult:
        """
        Bidirectional voice: speak text through speakers, then listen for response.

        1. Generate TTS audio from 'text' parameter
        2. Play it through speakers (auto-play)
        3. Listen via microphone for user's response
        4. Return both the spoken audio path and the transcribed response
        """
        text = kwargs.get("text", "").strip()
        if not text:
            return ToolResult(success=False, error="Missing 'text' — what should I say?")

        # Step 1: Speak (generates + auto-plays)
        speak_result = await self._speak(kwargs)
        if not speak_result.success:
            return speak_result

        # Step 2: Listen for the user's response
        listen_kwargs = {
            "lang": kwargs.get("lang", self._current_lang),
            "duration": kwargs.get("duration", 5.0),
        }
        listen_result = await self._listen(listen_kwargs)

        # Combine results
        spoken_output = speak_result.output if isinstance(speak_result.output, dict) else {}
        if listen_result.success:
            transcribed = listen_result.output if isinstance(listen_result.output, dict) else {}
            return ToolResult(
                success=True,
                output={
                    "spoken": spoken_output,
                    "user_response": transcribed.get("text", ""),
                    "user_language": transcribed.get("language", ""),
                    "mode": "conversation",
                },
                metadata={"engine_tts": "kokoro-82m", "engine_stt": "moonshine-v2"},
            )
        else:
            # Speech worked but listen failed — still return what we spoke
            return ToolResult(
                success=True,
                output={
                    "spoken": spoken_output,
                    "user_response": None,
                    "listen_error": listen_result.error,
                    "mode": "conversation",
                },
                metadata={"engine_tts": "kokoro-82m", "note": "STT failed but speech succeeded"},
            )

    # ----------------------------------------------------------------
    # Action: clone_speak — Chatterbox voice cloning (optional)
    # ----------------------------------------------------------------

    async def _clone_speak(self, kwargs: dict) -> ToolResult:
        """
        Generate speech using a cloned voice via Chatterbox-Turbo.
        
        OPTIONAL — only loaded if user explicitly requests voice cloning.
        Requires ~2GB VRAM. Will warn if hardware is limited.
        """
        text = kwargs.get("text", "").strip()
        ref_audio = kwargs.get("reference_audio", "").strip()

        if not text:
            return ToolResult(success=False, error="Missing 'text' parameter")
        if not ref_audio:
            return ToolResult(
                success=False,
                error=(
                    "Missing 'reference_audio' parameter. "
                    "Provide a path to a WAV/MP3 file of the voice to clone "
                    "(10-30 seconds recommended)."
                ),
            )

        ref_path = Path(ref_audio)
        if not ref_path.exists():
            return ToolResult(
                success=False,
                error=f"Reference audio not found: {ref_audio}",
            )

        # Lazy-load Chatterbox
        if self._chatterbox_model is None:
            try:
                from chatterbox.tts import ChatterboxTTS
                import torch

                # Check available VRAM
                if torch.cuda.is_available():
                    vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024**3)
                    if vram_gb < 2.0:
                        return ToolResult(
                            success=False,
                            error=(
                                f"Voice cloning requires ~2GB VRAM but your GPU has "
                                f"{vram_gb:.1f}GB. Use 'speak' action (Kokoro) instead, "
                                f"which only needs ~500MB."
                            ),
                        )
                    device = "cuda"
                else:
                    device = "cpu"
                    logger.warning("[VOICE] No GPU — Chatterbox will run on CPU (slow)")

                self._chatterbox_model = ChatterboxTTS.from_pretrained(device=device)
                logger.info(f"[VOICE] Chatterbox loaded on {device}")

            except ImportError:
                return ToolResult(
                    success=False,
                    error=(
                        "chatterbox-tts is not installed. Run: pip install chatterbox-tts\n"
                        "This is OPTIONAL — for standard speech, use action='speak' instead."
                    ),
                )

        # Generate cloned speech
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        start = time.time()

        try:
            import torchaudio

            wav = self._chatterbox_model.generate(
                text, audio_prompt_path=str(ref_path)
            )

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = kwargs.get("filename", f"kronos_clone_{timestamp}")
            filepath = _AUDIO_DIR / f"{filename}.wav"
            torchaudio.save(str(filepath), wav, self._chatterbox_model.sr)

            elapsed = (time.time() - start) * 1000
            duration_s = wav.shape[-1] / self._chatterbox_model.sr

            return ToolResult(
                success=True,
                output={
                    "path": str(filepath),
                    "duration_seconds": round(duration_s, 2),
                    "sample_rate": self._chatterbox_model.sr,
                    "reference_audio": str(ref_path),
                    "text_length": len(text),
                },
                metadata={
                    "path": str(filepath),
                    "elapsed_ms": round(elapsed, 0),
                    "engine": "chatterbox-turbo-350m",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Chatterbox error: {e}")

    # ----------------------------------------------------------------
    # Action: list_voices — show available voices
    # ----------------------------------------------------------------

    async def _list_voices(self, kwargs: dict) -> ToolResult:
        """List available voices for the current or specified language."""
        lang = kwargs.get("lang", self._current_lang)

        # Known Kokoro voices per language
        voices = {
            "en": [
                "af_heart", "af_bella", "af_nicole", "af_aoede", "af_kore",
                "af_sarah", "af_nova", "af_sky", "af_river",
                "am_adam", "am_michael", "am_fenrir", "am_puck", "am_echo",
            ],
            "en-gb": ["bf_emma", "bf_isabella", "bm_george", "bm_lewis", "bm_fable"],
            "es": ["ef_dora", "em_alex", "em_santa"],
            "fr": ["ff_siwis", "fm_gilles"],
            "ja": ["jf_alpha", "jf_gongitsune", "jm_kumo"],
            "ko": ["kf_yunju", "km_chae"],
            "zh": ["zf_xiaobei", "zf_xiaoni", "zm_yunjian"],
            "hi": ["hf_alpha", "hm_omega"],
            "it": ["if_sara", "im_nicola"],
            "pt-br": ["pf_dora", "pm_alex"],
        }

        lang_voices = voices.get(lang, [])
        default = DEFAULT_VOICES.get(lang, "")

        return ToolResult(
            success=True,
            output={
                "language": lang,
                "current_voice": self._current_voice,
                "default_voice": default,
                "available_voices": lang_voices,
                "total": len(lang_voices),
                "note": (
                    "Voice names: first letter = language, "
                    "second letter = f(female)/m(male), "
                    "then underscore + name"
                ),
            },
        )

    # ----------------------------------------------------------------
    # Action: set_voice
    # ----------------------------------------------------------------

    async def _set_voice(self, kwargs: dict) -> ToolResult:
        voice = kwargs.get("voice", "").strip()
        if not voice:
            return ToolResult(success=False, error="Missing 'voice' parameter")

        old_voice = self._current_voice
        self._current_voice = voice

        # Reset pipeline to pick up voice change
        self._kokoro_pipeline = None

        return ToolResult(
            success=True,
            output=f"Voice changed: {old_voice} → {voice}",
        )

    # ----------------------------------------------------------------
    # Action: set_lang
    # ----------------------------------------------------------------

    async def _set_lang(self, kwargs: dict) -> ToolResult:
        lang = kwargs.get("lang", "").strip()
        if not lang:
            return ToolResult(success=False, error="Missing 'lang' parameter")

        if lang not in KOKORO_LANGUAGES:
            return ToolResult(
                success=False,
                error=f"Unsupported language: {lang}. Supported: {list(KOKORO_LANGUAGES.keys())}",
            )

        old_lang = self._current_lang
        self._current_lang = lang
        self._current_voice = DEFAULT_VOICES.get(lang, self._current_voice)

        # Reset pipeline for new language
        self._kokoro_pipeline = None

        return ToolResult(
            success=True,
            output={
                "language_changed": f"{old_lang} → {lang}",
                "active_voice": self._current_voice,
            },
        )
