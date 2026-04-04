"""file_manager.py の単体テスト"""
import os
import pytest
from file_manager import save_meeting_log, generate_docx


@pytest.fixture
def sample_transcripts():
    return [
        {"source": "speaker", "text": "今日の議題は売上についてです", "timestamp": "2024-01-15T10:00:00"},
        {"source": "mic", "text": "了解しました", "timestamp": "2024-01-15T10:01:00"},
    ]


@pytest.fixture
def sample_advices():
    return [
        {"trigger_condition": "売上", "advice_text": "前年比のデータを提示してください"},
    ]


class TestSaveMeetingLog:
    def test_creates_markdown_file(self, tmp_path, sample_transcripts):
        """Markdownファイルが正常に作成される"""
        result = save_meeting_log(
            save_dir=str(tmp_path),
            session_title="テスト会議",
            transcripts=sample_transcripts,
            start_time="2024-01-15T10:00:00",
        )
        assert result is not None
        assert os.path.exists(result)
        assert result.endswith(".md")

    def test_markdown_contains_title(self, tmp_path, sample_transcripts):
        """Markdownにタイトルが含まれる"""
        result = save_meeting_log(
            save_dir=str(tmp_path),
            session_title="重要会議",
            transcripts=sample_transcripts,
        )
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# 重要会議" in content

    def test_markdown_contains_summary(self, tmp_path, sample_transcripts):
        """サマリーがある場合はMarkdownに含まれる"""
        result = save_meeting_log(
            save_dir=str(tmp_path),
            session_title="test",
            transcripts=sample_transcripts,
            summary="これはサマリーです",
        )
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "これはサマリーです" in content

    def test_markdown_contains_transcripts(self, tmp_path, sample_transcripts):
        """文字起こしがMarkdownに含まれる"""
        result = save_meeting_log(
            save_dir=str(tmp_path),
            session_title="test",
            transcripts=sample_transcripts,
        )
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "今日の議題は売上についてです" in content
        assert "了解しました" in content

    def test_markdown_contains_advices(self, tmp_path, sample_transcripts, sample_advices):
        """アドバイスがMarkdownに含まれる"""
        result = save_meeting_log(
            save_dir=str(tmp_path),
            session_title="test",
            transcripts=sample_transcripts,
            advices=sample_advices,
        )
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "売上" in content
        assert "前年比のデータを提示してください" in content

    def test_creates_directory_if_not_exists(self, tmp_path, sample_transcripts):
        """保存先ディレクトリが存在しない場合は作成される"""
        save_dir = str(tmp_path / "nested" / "dir")
        result = save_meeting_log(
            save_dir=save_dir,
            session_title="test",
            transcripts=sample_transcripts,
        )
        assert result is not None
        assert os.path.exists(result)


class TestGenerateDocx:
    def test_generates_docx_object(self, sample_transcripts):
        """Docxオブジェクトが正常に生成される"""
        doc = generate_docx(
            session_title="テストDocx",
            transcripts=sample_transcripts,
        )
        assert doc is not None

    def test_docx_has_title(self, sample_transcripts):
        """Docxにタイトルが含まれる"""
        doc = generate_docx(
            session_title="Docxタイトル",
            transcripts=sample_transcripts,
        )
        # 最初のparagraphがタイトル
        assert "Docxタイトル" in doc.paragraphs[0].text

    def test_docx_with_summary(self, sample_transcripts):
        """サマリー付きDocx"""
        doc = generate_docx(
            session_title="test",
            transcripts=sample_transcripts,
            summary="テストサマリー",
        )
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "テストサマリー" in all_text

    def test_docx_with_advices(self, sample_transcripts, sample_advices):
        """アドバイス付きDocx"""
        doc = generate_docx(
            session_title="test",
            transcripts=sample_transcripts,
            advices=sample_advices,
        )
        all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "売上" in all_text
