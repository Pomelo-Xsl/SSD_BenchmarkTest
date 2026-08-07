"""输出 SSD BenchmarkTest 的可复核源代码行数统计。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def count(folder:Path)->tuple[int,int]:
    files=list(folder.rglob("*.py"));return len(files),sum(len(file.read_text(encoding="utf-8").splitlines()) for file in files)
if __name__=="__main__":
    app_files,app_lines=count(ROOT/"app");test_files,test_lines=count(ROOT/"tests")
    print(f"后端 Python：{app_files} 个文件，{app_lines} 行")
    print(f"测试 Python：{test_files} 个文件，{test_lines} 行")
    print(f"Python 合计：{app_lines+test_lines} 行")
