"""The release workflow publishes what the build workflows build, for the
version the app reports. These checks keep the pieces from drifting apart:
a tag that fails release.yml's own check only fails after it is pushed."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _version() -> str:
    text = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def test_the_current_version_has_release_notes():
    notes = ROOT / ".github" / "release-notes" / f"v{_version()}.md"
    assert notes.is_file() and notes.read_text(encoding="utf-8").strip(), (
        f"release.yml refuses a tag without {notes.relative_to(ROOT)}"
    )


def test_the_version_is_a_plain_release_number():
    # The update checker compares versions numerically; a suffix it cannot
    # parse would make every release look older than the one installed.
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version())


def test_every_workflow_the_release_calls_can_be_called():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    called = re.findall(r"uses:\s*\./\.github/workflows/([\w.-]+\.yml)", release)
    assert set(called) == {"test.yml", "build-windows.yml", "build-windows-full.yml",
                           "build-linux.yml", "build-macos-dmg.yml"}
    for name in called:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert re.search(r"^\s+workflow_call:", text, re.M), f"{name} cannot be called by release.yml"
        # The manual button stays.
        assert "workflow_dispatch" in text, name


def test_the_release_publishes_exactly_what_the_builds_upload():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    published = set(re.findall(r"dist/(ToonStudio-[\w.-]+)", release))
    built = set()
    for name in ("build-windows.yml", "build-windows-full.yml", "build-linux.yml", "build-macos-dmg.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        upload = text[text.index("upload-artifact"):]
        built |= set(re.findall(r"dist/(ToonStudio-[\w.-]+)", upload))
    assert published == built and len(built) == 6


def test_the_release_runs_on_a_version_tag_or_by_hand_never_on_its_own():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    on_block = release[release.index("\non:"):release.index("\npermissions:")]
    assert "tags: ['v*']" in on_block
    assert "workflow_dispatch" in on_block
    assert "branches" not in on_block and "pull_request" not in on_block


def test_a_manual_release_takes_its_tag_from_the_version_and_never_reuses_one():
    """Run by hand there is no tag yet: the release must create v<version> on
    the commit it built, and refuse a version that was already released."""
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert 'tag="v${version}"' in release
    assert "git ls-remote --exit-code --tags origin" in release, "an existing tag must be refused"
    assert "tag_name: ${{ needs.check.outputs.tag }}" in release
    assert "target_commitish: ${{ github.sha }}" in release
    assert 'notes=".github/release-notes/${tag}.md"' in release
    assert "body_path: ${{ needs.check.outputs.notes }}" in release


def test_a_test_build_is_a_pre_release_nobody_is_offered_as_an_update():
    """Run by hand on any branch with "prerelease" ticked: a fresh tag per run,
    its own notes, marked pre-release and never latest. The update checker asks
    /releases/latest, which GitHub answers with the newest non-pre-release."""
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    on_block = release[release.index("\non:"):release.index("\npermissions:")]
    assert "prerelease:" in on_block and "default: false" in on_block
    assert 'tag="v${version}-beta.${GITHUB_RUN_NUMBER}"' in release
    assert 'notes=".github/release-notes/beta.md"' in release
    assert (ROOT / ".github" / "release-notes" / "beta.md").read_text(encoding="utf-8").strip()
    check = release[release.index('if [ "${PRERELEASE}" = "true" ]'):release.index('elif [ "${GITHUB_EVENT_NAME}" = "push" ]')]
    assert "main" not in check, "a test build may come from any branch"
    assert "prerelease: ${{ needs.check.outputs.prerelease == 'true' }}" in release
    assert "make_latest: ${{ needs.check.outputs.prerelease == 'true' && 'false' || 'true' }}" in release
    checker = (ROOT / "app" / "update_checker.py").read_text(encoding="utf-8")
    assert "/releases/latest" in checker


def test_a_release_does_not_share_main_ci_concurrency_group():
    """test.yml cancels older runs in its group; keyed on the branch alone, a
    release run from main and main's own CI would cancel each other."""
    tests = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    assert "group: tests-${{ github.workflow }}-" in tests


def test_the_dmg_is_signed_after_its_plist_is_edited_and_tested_as_shipped():
    """Editing Info.plist breaks PyInstaller's ad-hoc signature, and Apple
    Silicon will not run code whose signature does not match; and what users
    get is the DMG, so the copy inside it is what has to start."""
    text = (WORKFLOWS / "build-macos-dmg.yml").read_text(encoding="utf-8")
    plist = text.index("plutil -replace CFBundleShortVersionString")
    sign = text.index("codesign --force --deep --sign -")
    assert plist < sign < text.index("codesign --verify")
    dmg = text.index("hdiutil create")
    mounted = text.index("hdiutil attach")
    assert dmg < mounted < text.index('"$mount/Toon Studio.app/Contents/MacOS/ToonStudio" --skia-self-test')
    assert 'ln -s /Applications "$stage/Applications"' in text
    # The release attaches the DMG; an older release gets it by hand.
    assert "gh release upload \"$TAG\" dist/ToonStudio-macOS-arm64.dmg" in text


def test_a_release_goes_out_without_the_dmg_when_only_macos_failed():
    # 3.1.1: the macOS job was cancelled twice after 15 minutes in the queue
    # with no runner, and the release that waited on all three builds was
    # skipped although Windows and Linux had passed.
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    publish = release.split("\n  publish:\n", 1)[1]
    condition = publish.split("runs-on:", 1)[0]
    assert "always()" in condition
    for job in ("check", "tests", "windows", "linux"):
        assert f"needs.{job}.result == 'success'" in condition
    assert "needs.macos.result ==" not in condition
    # Windows and Linux are still required files; only the DMG is optional.
    assert ("ls dist/ToonStudio-Windows-x86_64-Setup.exe dist/ToonStudio-Windows-x86_64.zip "
            "dist/ToonStudio-Linux-x86_64.tar.gz") in publish
    assert "fail_on_unmatched_files: true" in publish


def test_the_full_windows_build_is_optional_and_proven_to_run():
    """The full build (PyTorch, EasyOCR, PaddleOCR-VL) rides along with a
    release but never holds one up, and is refused over GitHub's 2 GB limit
    rather than failing the upload of everything else."""
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    publish = release.split("\n  publish:\n", 1)[1]
    condition = publish.split("runs-on:", 1)[0]
    assert "windows_full" in publish.split("\n", 1)[0]          # waited for…
    assert "needs.windows_full.result ==" not in condition       # …never required
    assert 'full=dist/ToonStudio-Windows-x86_64-full.zip' in publish
    assert '[ -n "$full" ] && echo "$full"' in publish
    full = (WORKFLOWS / "build-windows-full.yml").read_text(encoding="utf-8")
    assert "pip install easyocr" in full and "--collect-all easyocr" in full
    assert "--optional-ocr-self-test" in full
    assert "2147483648" in full
    # The probe checks the packages the app's own availability check asks for.
    import comic
    settings_ui = (ROOT / "app" / "ui" / "settings" / "settings_ui.py").read_text(encoding="utf-8")
    for package in ("torch", "torchvision", "transformers", "easyocr"):
        assert package in comic.OPTIONAL_OCR_PACKAGES
        assert f'"{package}"' in settings_ui


def test_the_linux_build_runs_on_a_named_ubuntu_release():
    """`ubuntu-latest` moves. When it reached 26.04 the 3.3.1 release failed in
    "Set up Python": the pinned interpreter has no build for that image, so the
    required Linux archive was never made and nothing was published. The
    runner also sets the oldest glibc the bundle starts on."""
    text = (WORKFLOWS / "build-linux.yml").read_text(encoding="utf-8")
    runner = re.search(r"^\s+runs-on:\s*(\S+)", text, re.M).group(1)
    assert re.fullmatch(r"ubuntu-\d\d\.\d\d", runner), runner


def test_the_windows_installers_are_built_tested_and_published():
    iss = (ROOT / "installer" / "toonstudio.iss").read_text(encoding="utf-8")
    build_ps = (ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")
    test_ps = (ROOT / "installer" / "test_installer.ps1").read_text(encoding="utf-8")
    # One script, two editions, each named as the workflows upload it.
    assert '#define SetupName "ToonStudio-Windows-x86_64-Setup"' in iss
    assert '#define SetupName "ToonStudio-Windows-x86_64-full-Setup"' in iss
    assert "OutputBaseFilename={#SetupName}" in iss
    assert '"/DAppVersion=$version" "/DEdition=$Edition"' in build_ps
    assert "2147483648" in build_ps                         # GitHub's asset limit
    # Installed, run and uninstalled on the runner, not only compiled.
    for word in ("/VERYSILENT", "/CURRENTUSER", "unins000.exe", "ToonStudio.Project"):
        assert word in test_ps, word
    for name, edition, setup, extra in (
        ("build-windows.yml", "lean", "ToonStudio-Windows-x86_64-Setup.exe", None),
        ("build-windows-full.yml", "full", "ToonStudio-Windows-x86_64-full-Setup.exe", "--optional-ocr-self-test"),
    ):
        build = (WORKFLOWS / name).read_text(encoding="utf-8")
        built = build.index(f"build_installer.ps1 -Edition {edition}")
        # Built from the folder that passed the bundle's own self-tests…
        assert build.index("--skia-self-test") < built, name
        # …then installed and tested as installed.
        tested = build.index(f"test_installer.ps1 -Setup dist/{setup}")
        assert built < tested < build.index("upload-artifact"), name
        if extra:
            assert extra in build[tested:build.index("upload-artifact")], name
    # Per user, no administrator prompt, so the updater can run the next one;
    # one AppId for both editions, so either replaces the other.
    assert "PrivilegesRequired=lowest" in iss
    assert iss.count("AppId=") == 1 and "AppId={{6B0E4C7A-3F2D-4B8E-9C51-7A2E8D4F1C93}" in iss
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    # The lean installer is required like the zip; the full one is optional
    # like the full zip, and only goes out beside it.
    assert "ls dist/ToonStudio-Windows-x86_64-Setup.exe" in release
    assert 'full_setup=dist/ToonStudio-Windows-x86_64-full-Setup.exe' in release
    assert '[ -z "$full" ] || [ ! -f "$full_setup" ]' in release
