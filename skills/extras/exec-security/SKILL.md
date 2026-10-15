---
name: exec-security
description: Execution skill loaded when modifying auth, API endpoints, data access, or user inputs.
---
# Security Execution Strategy

When touching sensitive areas of the codebase, strictly adhere to this security checklist:

1. **Input Validation**: Never trust user input. Ensure all incoming data is validated and typed before processing.
2. **Output Sanitization**: Prevent XSS by sanitizing data before it reaches the UI.
3. **Authorization**: Verify the user has the correct permissions (not just authentication) to perform the action or access the data.
4. **Secrets Management**: Never hardcode API keys, tokens, or passwords. Ensure they are loaded from environment variables or secure vaults.
5. **SQL/NoSQL Injection**: Always use parameterized queries or ORM methods that automatically escape inputs.

Do not merge any code that bypasses these checks. If you discover a pre-existing security flaw during your work, flag it immediately.
