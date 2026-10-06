import subprocess


def select_diarized_speaker(start_sec, end_sec, diarization_turns):
    """Map one ASR segment to its dominant anonymous diarization label."""
    overlaps = {}
    for turn_start, turn_end, speaker in diarization_turns:
        overlap = max(0.0, min(end_sec, turn_end) - max(start_sec, turn_start))
        if overlap:
            overlaps[speaker] = overlaps.get(speaker, 0.0) + overlap
    if not overlaps:
        return "UNKNOWN"
    ordered = sorted(overlaps.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) > 1 and ordered[1][1] >= ordered[0][1] * 0.8:
        return "SPEAKER_MIXED"
    return ordered[0][0]


def decode_audio_to_pyannote_waveform(audio_path, ffmpeg_bin, torch_module):
    """Decode mono 16 kHz PCM with FFmpeg, avoiding TorchCodec file decoding."""
    result = subprocess.run(
        [
            ffmpeg_bin, "-v", "error", "-i", audio_path, "-vn",
            "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "FFmpeg가 오디오를 디코딩하지 못했습니다.")
    if not result.stdout or len(result.stdout) % 2:
        raise RuntimeError("FFmpeg에서 유효한 16-bit PCM 오디오를 받지 못했습니다.")

    pcm_buffer = bytearray(result.stdout)
    del result
    pcm_int16 = torch_module.frombuffer(pcm_buffer, dtype=torch_module.int16)
    waveform = pcm_int16.to(dtype=torch_module.float32).div_(32768.0).unsqueeze(0)
    del pcm_int16, pcm_buffer
    return waveform
