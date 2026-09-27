import pytest

from tests.synth import make_scroll_video, make_video


@pytest.fixture(scope="session")
def synth_video(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("synth") / "synth.avi")


@pytest.fixture(scope="session")
def synth_video_dark(tmp_path_factory):
    return make_video(tmp_path_factory.mktemp("synth_dark") / "synth_dark.avi", dark=True)


@pytest.fixture(scope="session")
def scroll_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("scroll") / "scroll.avi"
    make_scroll_video(path)
    return path
