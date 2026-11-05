import tts_request
from cues import ReplyParser, StreamSegmenter
from tts_request import ENGINE_CPP, ENGINE_PYTORCH, request_body


def test_defaults_to_meanflow_on_speech_cpp_at_6_steps():
    assert tts_request.ENGINE == ENGINE_CPP
    assert tts_request.MODEL == "irodori-tts-mf"
    assert tts_request.STEPS == 6
    assert tts_request.DEFAULT_VOICE == ""


def test_meanflow_request_leaves_out_settings_it_refuses():
    assert request_body("テスト", "my-voice", engine=ENGINE_CPP, steps=6, model="irodori-tts-mf") == {
        "input": "テスト",
        "voice": "my-voice",
        "response_format": "wav",
        "steps": 6,
    }


def test_quantized_meanflow_is_still_meanflow():
    assert "sway_coeff" not in request_body("テスト", "my-voice", engine=ENGINE_CPP, model="irodori-tts-mf:q8_0")


def test_other_cpp_models_get_sway_and_guidance():
    assert request_body("テスト", "my-voice", engine=ENGINE_CPP, steps=20, model="irodori-tts") == {
        "input": "テスト",
        "voice": "my-voice",
        "response_format": "wav",
        "steps": 20,
        "sway_coeff": -1.0,
        "cfg_guidance_mode": "independent",
    }


def test_cpp_request_carries_optional_settings():
    body = request_body("テスト", "my-voice", seed=3, speed=1.2, caption="優しく", engine=ENGINE_CPP)
    assert (body["seed"], body["speed"], body["instructions"]) == (3, 1.2, "優しく")


def test_pytorch_request_keeps_the_server_format():
    body = request_body("テスト", "my-voice-latent", seed=3, engine=ENGINE_PYTORCH, steps=40)
    assert body["model"] == "irodori-tts"
    assert body["irodori"] == {
        "chunking_enabled": False,
        "num_steps": 40,
        "t_schedule_mode": "sway",
        "sway_coeff": -1.0,
        "cfg_guidance_mode": "independent",
        "seed": 3,
    }


def test_steps_can_be_changed():
    assert request_body("テスト", "my-voice", engine=ENGINE_CPP, steps=40)["steps"] == 40


def test_one_character_minimum_sends_each_sentence_alone():
    segmenter = StreamSegmenter(min_chars=1)
    assert segmenter.feed("えっ！もうリーチなの？ちょっと") == ["えっ！", "もうリーチなの？"]
    assert segmenter.flush() == ["ちょっと"]


def test_parser_passes_its_minimum_to_the_segmenter():
    parser = ReplyParser(min_segment_chars=1)
    assert parser.feed("えっ！🤭もう").segments == ["えっ！"]
    assert parser.finish().segments == ["🤭もう"]


def test_duration_scale_is_only_sent_when_changed():
    assert "duration_scale" not in request_body("テスト", "my-voice", engine=ENGINE_CPP, duration_scale=1)
    assert request_body("テスト", "my-voice", engine=ENGINE_CPP, duration_scale=0.7)["duration_scale"] == 0.7
    assert request_body("テスト", "my-voice-latent", engine=ENGINE_PYTORCH, duration_scale=0.7)["irodori"]["duration_scale"] == 0.7
