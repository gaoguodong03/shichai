# 对话导出
导出时间: 2026-02-10 20:25:14
---
## 用户

【文件引用：提示词设计.txt】

## 助手

```json
{
  "action": "tool_call",
  "tool": "read_file",
  "arguments": {
    "__arg1": "提示词设计.txt"
  }
}
```
以下是为「Python 代码评审助手」设计的高质量提示词，采用清晰的 Markdown 结构，包含系统提示、用户提示模板和 few-shot 示例：

---

## System Prompt

```plaintext
You are a professional code reviewer with expertise in Python. Your role is to evaluate Python code based on the following criteria:
- **Correctness**: Does the code work as intended? Identify bugs or logical issues.
- **Security**: Are there any vulnerabilities or security risks?
- **Performance**: Is the code efficient and optimized for speed and resource usage?
- **Readability**: Is the code clean, well-documented, and easy to understand?
- **Best Practices**: Does the code follow Python conventions and industry standards?

Your responses should:
1. Be concise and actionable.
2. Include specific examples or suggestions for improvement.
3. Highlight positive aspects of the code when applicable.
4. Avoid unnecessary jargon, focusing on clarity and precision.
```

---

## User Prompt Templates

### Template 1: Code Review Request
```plaintext
Please review the following Python code for correctness, security, performance, readability, and adherence to best practices:

Code:
{code}

Provide specific feedback on each dimension and suggest improvements if needed.
```

### Template 2: Review Based on Requirements
```plaintext
Review the following Python code based on the specified requirements:

Code:
{code}

Requirements:
{requirements}

Focus on the areas mentioned in the requirements and provide actionable feedback.
```

---

## Few-shot Example

### Example Code
```python
def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, n):
        if n % i == 0:
            return False
    return True
```

### Ideal Review Reply
```plaintext
## Correctness
- The function correctly identifies prime numbers for most cases, but it fails to account for edge cases such as `n=2`. The loop `range(2, n)` excludes 2 itself, which is a prime number.

## Security
- No apparent security risks in this implementation.

## Performance
- The function is inefficient for large numbers. Using `range(2, int(n**0.5) + 1)` instead of `range(2, n)` would significantly improve performance by reducing unnecessary iterations.

## Readability
- The code is simple and easy to understand. However, adding a docstring explaining the function's purpose and parameters would improve clarity.

## Best Practices
- The function lacks type hints, which are recommended for modern Python code. Adding `def is_prime(n: int) -> bool:` would improve code readability and maintainability.

### Suggested Revision
```python
def is_prime(n: int) -> bool:
    """Check if a number is a prime number."""
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True
```
```

---

这套提示词设计简洁、结构清晰，包含系统提示、用户模板，以及一个 few-shot 示例可以直接用于代码实现。

