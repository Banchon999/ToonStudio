"""Which folders and files are chapters, what they are called, and resume."""

import os

from core import chapter_queue as cq


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")


def test_a_folder_of_images_is_one_chapter(tmp_path):
    _touch(str(tmp_path / "ch1" / "001.png"))
    _touch(str(tmp_path / "ch1" / "extra" / "002.jpg"))
    assert cq.find_chapters(str(tmp_path / "ch1")) == [os.path.normpath(str(tmp_path / "ch1"))]
    assert [os.path.basename(p) for p in cq.images_in(str(tmp_path / "ch1"))] == ["001.png", "002.jpg"]


def test_a_series_folder_lists_its_chapters_in_natural_order(tmp_path):
    for name in ("ตอนที่ 10", "ตอนที่ 2", "ตอนที่ 1"):
        _touch(str(tmp_path / name / "01.png"))
    os.makedirs(tmp_path / "empty")                      # no images: not a chapter
    _touch(str(tmp_path / "ตอนที่ 3.cbz"))
    _touch(str(tmp_path / "notes.txt"))
    found = [os.path.basename(p) for p in cq.find_chapters(str(tmp_path))]
    assert found == ["ตอนที่ 1", "ตอนที่ 2", "ตอนที่ 3.cbz", "ตอนที่ 10"]


def test_an_archive_is_a_chapter_and_other_files_are_not(tmp_path):
    _touch(str(tmp_path / "a.cbz"))
    _touch(str(tmp_path / "b.txt"))
    assert cq.find_chapters(str(tmp_path / "a.cbz")) == [os.path.normpath(str(tmp_path / "a.cbz"))]
    assert cq.find_chapters(str(tmp_path / "b.txt")) == []
    assert cq.find_chapters(str(tmp_path / "missing")) == []


def test_names_are_unique_and_safe_and_sources_are_not_queued_twice(tmp_path):
    a = str(tmp_path / "s1" / "Chapter 1")
    b = str(tmp_path / "s2" / "chapter 1")
    c = str(tmp_path / "s3" / "Ch:2.cbz")
    _touch(c)
    chapters = cq.make_chapters([a, b, c])
    assert [ch.name for ch in chapters] == ["Chapter 1", "chapter 1 (2)", "Ch_2"]
    again = cq.make_chapters([a, str(tmp_path / "s4")], chapters)
    assert [ch.name for ch in again] == ["s4"]


def test_output_paths(tmp_path):
    ch = cq.Chapter(source="/x/ep 5", name="ep 5")
    out = str(tmp_path)
    assert cq.project_path(out, ch) == os.path.join(out, "ep 5.ctpr")
    assert cq.export_path(out, ch, "folder") == os.path.join(out, "ep 5")
    assert cq.export_path(out, ch, "cbz") == os.path.join(out, "ep 5.cbz")
    assert cq.export_path(out, ch, "none") is None


def test_only_a_cleanly_finished_chapter_from_the_same_source_is_done(tmp_path):
    out = str(tmp_path / "out")
    os.makedirs(out)
    ch = cq.Chapter(source=str(tmp_path / "ep1"), name="ep1")
    assert not cq.already_done(out, ch)

    ch.status = cq.DONE
    cq.save_progress(out, ch)
    assert not cq.already_done(out, ch)              # its project file is gone
    _touch(cq.project_path(out, ch))
    assert cq.already_done(out, ch)

    other = cq.Chapter(source=str(tmp_path / "elsewhere"), name="ep1")
    assert not cq.already_done(out, other)          # same name, another source

    for status in (cq.REVIEW, cq.FAILED, cq.STOPPED, cq.RUNNING):
        ch.status = status
        cq.save_progress(out, ch)
        assert not cq.already_done(out, ch), status


def test_an_interrupted_chapter_resumes_from_its_project_only_if_ours(tmp_path):
    out = str(tmp_path)
    ch = cq.Chapter(source=str(tmp_path / "ep1"), name="ep1")
    _touch(cq.project_path(out, ch))
    assert cq.resumable_project(out, ch) is None    # someone else's file of that name
    ch.status = cq.RUNNING
    cq.save_progress(out, ch)
    assert cq.resumable_project(out, ch) == cq.project_path(out, ch)


def test_a_broken_progress_file_reads_as_nothing_done(tmp_path):
    (tmp_path / cq.PROGRESS_FILE).write_text("{not json", encoding="utf-8")
    assert cq.load_progress(str(tmp_path)) == {}
