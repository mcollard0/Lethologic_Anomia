#!/usr/bin/env python3
"""
Analyze Python codebase to count lines that are:
- Not comments
- Not strings
- Do not end with semicolons
"""

import os
import re
import ast
import tokenize
from io import StringIO

def is_code_line(line, in_multiline_string=False):
    """Check if a line contains actual code (not just comments or strings)"""
    line = line.strip()
    
    # Skip empty lines
    if not line:
        return False, in_multiline_string
    
    # Skip pure comment lines
    if line.startswith('#'):
        return False, in_multiline_string
    
    # Check for multiline strings
    if '"""' in line or "'''" in line:
        triple_quote_count = line.count('"""') + line.count("'''")
        if triple_quote_count % 2 == 1:
            in_multiline_string = not in_multiline_string
        if line.strip().startswith('"""') or line.strip().startswith("'''"):
            return False, in_multiline_string
    
    # Skip lines in multiline strings
    if in_multiline_string:
        return False, in_multiline_string
    
    # Skip lines that are just string literals
    try:
        # Try to parse as Python code to see if it's just a string
        parsed = ast.parse(line)
        if len(parsed.body) == 1 and isinstance(parsed.body[0], ast.Expr):
            if isinstance(parsed.body[0].value, ast.Constant) and isinstance(parsed.body[0].value.value, str):
                return False, in_multiline_string
    except:
        pass
    
    return True, in_multiline_string

def analyze_file(filepath):
    """Analyze a single Python file"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        code_lines = 0
        lines_without_semicolon = 0
        in_multiline_string = False
        
        for line in lines:
            is_code, in_multiline_string = is_code_line(line, in_multiline_string)
            
            if is_code:
                code_lines += 1
                # Check if the line doesn't end with semicolon
                if not line.rstrip().endswith(';'):
                    lines_without_semicolon += 1
        
        return code_lines, lines_without_semicolon
    
    except Exception as e:
        print(f"Error analyzing {filepath}: {e}")
        return 0, 0

def main():
    """Main analysis function"""
    python_files = []
    
    # Find all Python files
    for root, dirs, files in os.walk('.'):
        # Skip venv directory
        if 'venv' in root or '__pycache__' in root:
            continue
            
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    
    total_code_lines = 0
    total_lines_without_semicolon = 0
    
    print("Analyzing Python files...")
    print("=" * 50)
    
    for filepath in sorted(python_files):
        code_lines, lines_without_semicolon = analyze_file(filepath)
        total_code_lines += code_lines
        total_lines_without_semicolon += lines_without_semicolon
        
        print(f"{filepath}: {code_lines} code lines, {lines_without_semicolon} without semicolons")
    
    print("=" * 50)
    print(f"Total code lines: {total_code_lines}")
    print(f"Code lines without semicolons: {total_lines_without_semicolon}")
    print(f"Percentage without semicolons: {(total_lines_without_semicolon/total_code_lines)*100:.2f}%" if total_code_lines > 0 else "N/A")

if __name__ == "__main__":
    main()
