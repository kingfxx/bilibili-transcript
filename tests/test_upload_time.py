from bilibili_transcript.meta import with_upload_time
from bilibili_transcript.export_html import export_morandi_html


def test_upload_time_preserved_in_md_and_html(tmp_path):
    original = '# 常见的投资品种\n\n## 全文总结\n\n总结。\n\n## 1. 课程讲解\n\n### 1.1 主题\n\n正文。\n'
    data = {'pubdate': 1741180000}
    text = with_upload_time(original, data)
    assert '视频上传时间：2025-03-05 21:06:40（北京时间）' in text
    assert with_upload_time(text, data) == text
    md = tmp_path / 'notes.md'
    md.write_text(text, encoding='utf-8')
    html = export_morandi_html(md).read_text(encoding='utf-8')
    assert '视频上传时间：2025-03-05 21:06:40（北京时间）' in html
    assert '正文。' in html


def test_missing_timestamp_does_not_invent_date():
    text = '# 标题\n\n## 全文总结\n\n总结。'
    for data in [{}, {'pubdate': None}, {'pubdate': 0}, {'pubdate': True}]:
        assert with_upload_time(text, data) == text
