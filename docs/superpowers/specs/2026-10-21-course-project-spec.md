# Course project spec: domain-specific RAG chatbot with tool calling

Source: the course task description (pasted by the project owner on 2026-10-21). Domain chosen: **travel planning between two cities**, including flight routes and airlines, flight time, destination information and travel insurance.

## Task description
Create a specialised chatbot that uses advanced RAG techniques and tool calling to provide domain-specific assistance, using LangChain, Streamlit or Next.js, and advanced RAG techniques. The chatbot will:

1. Implement advanced RAG with query translation and structured retrieval
2. Include tool calling capabilities for practical tasks
3. Focus on a specific domain or use case
4. Provide detailed, context-aware responses

## Core requirements
1. RAG implementation
   - Create a knowledge base relevant to your domain
   - Implement standard document retrieval with embeddings
   - Use chunking strategies and similarity search
2. Tool calling
   - Implement at least 3 different tool calls
   - Functions should be relevant to your domain
   - Examples: data analysis, calculations, API integrations
3. Domain specialisation
   - Choose a specific domain or use case
   - Create a focused knowledge base
   - Implement domain-specific prompts and responses
   - Add relevant security measures for your domain
4. Technical implementation
   - Use LangChain with OpenRouter (OpenAI-compatible SDK) for LLM integration
   - Implement proper error handling
   - Include user input validation
5. User interface
   - Create an intuitive interface using Streamlit or Next.js
   - Show relevant context and sources
   - Display tool call results
   - Include progress indicators for long operations

## Optional tasks
Easy:
1. Add conversation history and export functionality
2. Add visualisation of RAG process
3. Include source citations in responses
4. Add an interactive help feature or chatbot guide

Medium:
1. Implement multi-model support (OpenAI, Anthropic, etc.)
2. Add real-time data updates to knowledge base
3. Protect your app against prompt injection
4. Add user authentication and personalisation
5. Calculate and display token usage and costs
6. Add visualisation of tool call results
7. Implement conversation export in various formats (PDF, CSV, JSON)
8. Connect to tools from a publicly available remote MCP server
9. Implement rate limiting and API key management
10. Add logging and monitoring

Hard:
1. Employ hybrid search
2. Implement A/B testing for different RAG strategies
3. Add automated knowledge base updates
4. Add multi-language support
5. Implement advanced analytics dashboard
6. Implement your tools (functions) as MCP servers
7. Implement an evaluation of your RAG system, using RAGAs or otherwise

## Evaluation criteria
- Understanding core concepts: how RAG works, how tool calling is implemented, good code organisation, error scenarios and edge cases.
- Technical implementation: front-end library use, the chatbot works and answers, a relevant knowledge base, appropriate security considerations.
- Reflection and improvement: understands the application's potential problems and can suggest improvements.
- Bonus: for maximum points, implement at least 2 medium and 1 hard optional task.
