import agent


def test_read_file_tool_reads_wiki_file():
    result = agent.read_file("wiki/git-workflow.md")
    assert "git workflow" in result.lower() or "pull request" in result.lower()


def test_list_files_tool_lists_wiki_directory():
    result = agent.list_files("wiki")
    assert "git-workflow.md" in result


def test_read_file_rejects_escape():
    result = agent.read_file("../etc/passwd")
    assert result.startswith("ERROR:")


def test_list_files_rejects_escape():
    result = agent.list_files("../")
    assert result.startswith("ERROR:")
