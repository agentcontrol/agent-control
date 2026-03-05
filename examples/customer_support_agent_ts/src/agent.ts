/**
 * Customer Support Agent — TypeScript SDK integration example.
 *
 * Demonstrates:
 *   1. SDK initialization
 *   2. Using control() HOF to protect async functions
 *   3. Handling ControlViolationError gracefully
 */

import agentControl, { control, ControlViolationError } from "agent-control";

import {
  generateLlmResponse,
  lookupCustomer,
  searchKnowledgeBase,
  createTicket,
} from "./mock-services.js";

// ---------------------------------------------------------------------------
// Protected functions — using control() HOF
// ---------------------------------------------------------------------------

/**
 * Main chat — LLM call protected with pre/post evaluation.
 *
 * Pre-check validates the user message (prompt injection, profanity, etc.)
 * Post-check validates the LLM response (PII leakage, toxicity, etc.)
 */
export const respondToCustomer = control(
  "respond_to_customer",
  async (message: string): Promise<string> => {
    return generateLlmResponse(message);
  },
);

/** Customer lookup — tool call. */
export const lookupCustomerTool = control(
  "lookup_customer",
  async (query: string) => {
    const customer = lookupCustomer(query);
    if (customer) return { found: true as const, customer };
    return {
      found: false as const,
      message: `No customer found for: ${query}`,
    };
  },
  { type: "tool" },
);

/** Knowledge base search — tool call. */
export const searchKnowledgeBaseTool = control(
  "search_knowledge_base",
  async (query: string) => {
    const articles = searchKnowledgeBase(query);
    return { query, resultsCount: articles.length, articles };
  },
  { type: "tool" },
);

/** Ticket creation — tool call. */
export const createTicketTool = control(
  "create_ticket",
  async (params: {
    subject: string;
    description: string;
    priority?: string;
  }) => {
    const ticket = createTicket(
      params.subject,
      params.description,
      params.priority,
    );
    return { success: true, ticket };
  },
  { type: "tool" },
);

// ---------------------------------------------------------------------------
// SDK Initialization (call once at startup)
// ---------------------------------------------------------------------------

const serverUrl = process.env.AGENT_CONTROL_URL ?? "http://localhost:8000";
const apiKey = process.env.AGENT_CONTROL_API_KEY;

/** Await this before using the agent so the server has steps registered (for UI dropdown). */
export const agentReady = agentControl.init({
  agentName: "customer-support-agent-ts",
  serverUrl,
  ...(apiKey ? { apiKey } : {}),
});

// ---------------------------------------------------------------------------
// Agent class — orchestrates protected functions with error handling
// ---------------------------------------------------------------------------

export class CustomerSupportAgent {
  private history: Array<{ role: string; content: string }> = [];

  async chat(userMessage: string): Promise<string> {
    this.history.push({ role: "user", content: userMessage });

    try {
      const response = await respondToCustomer(userMessage);
      this.history.push({ role: "assistant", content: response });
      return response;
    } catch (err) {
      const fallback = this.handleControlError(
        err,
        "I can't help with that request.",
      );
      this.history.push({ role: "assistant", content: fallback });
      return fallback;
    }
  }

  async lookup(query: string): Promise<string> {
    try {
      const result = await lookupCustomerTool(query);
      if (result.found) {
        const { name, email, tier } = result.customer;
        return `Found customer: ${name} (${email}) - ${tier} tier`;
      }
      return result.message;
    } catch (err) {
      return this.handleControlError(
        err,
        "I'm unable to process that lookup request.",
      );
    }
  }

  async search(query: string): Promise<string> {
    try {
      const result = await searchKnowledgeBaseTool(query);
      if (result.articles.length > 0) {
        const article = result.articles[0];
        return `Found: ${article.title}\n${article.content}`;
      }
      return "No relevant articles found.";
    } catch (err) {
      return this.handleControlError(
        err,
        "I'm unable to search for that query.",
      );
    }
  }

  async createSupportTicket(
    subject: string,
    description: string,
    priority = "medium",
  ): Promise<string> {
    try {
      const result = await createTicketTool({ subject, description, priority });
      if (result.success) {
        return `Ticket created: ${result.ticket.ticketId} (Priority: ${result.ticket.priority})`;
      }
      return "Failed to create ticket.";
    } catch (err) {
      return this.handleControlError(
        err,
        "I'm unable to create a ticket with that content.",
      );
    }
  }

  private handleControlError(err: unknown, fallback: string): string {
    if (err instanceof ControlViolationError) {
      console.log(`  [Control triggered: ${err.controlName}]`);
    } else {
      const msg = err instanceof Error ? err.message : String(err);
      console.log(`  [Blocked: ${msg}]`);
    }
    return fallback;
  }
}
