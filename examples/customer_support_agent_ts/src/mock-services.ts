/**
 * Mock services simulating real backend dependencies.
 * In production these would connect to actual LLMs, databases, and APIs.
 */

// ---------------------------------------------------------------------------
// Mock LLM
// ---------------------------------------------------------------------------

const LLM_RESPONSES: Record<string, string> = {
  greeting:
    "Hello! I'm your customer support assistant. How can I help you today?",
  refund:
    "I understand you'd like a refund. Let me look into your order. " +
    "Our refund policy allows returns within 30 days of purchase.",
  technical:
    "I can help with technical issues. Could you describe the problem " +
    "you're experiencing in more detail?",
  status:
    "I'll check the status of your order right away. " +
    "Could you provide your order number?",
  default: "Thank you for your message. Let me help you with that.",
};

export function generateLlmResponse(message: string): string {
  const lower = message.toLowerCase();
  if (/\b(hi|hello|hey)\b/.test(lower)) return LLM_RESPONSES.greeting;
  if (/\b(refund|return|money back)\b/.test(lower)) return LLM_RESPONSES.refund;
  if (/\b(error|bug|broken|not working)\b/.test(lower)) return LLM_RESPONSES.technical;
  if (/\b(status|order|tracking)\b/.test(lower)) return LLM_RESPONSES.status;
  // Simulate LLM naively returning a credit card — post control should block this
  if (/\b(credit\s*card|card\s*number)\b/.test(lower)) {
    return "Here is a test card number you can use: 4111-1111-1111-1111.";
  }
  return LLM_RESPONSES.default;
}

// ---------------------------------------------------------------------------
// Mock Customer Database
// ---------------------------------------------------------------------------

interface Customer {
  id: string;
  name: string;
  email: string;
  tier: string;
  orders: number;
}

const CUSTOMERS: Record<string, Customer> = {
  C001: { id: "C001", name: "Alice Smith", email: "alice@example.com", tier: "premium", orders: 15 },
  C002: { id: "C002", name: "Bob Johnson", email: "bob@example.com", tier: "standard", orders: 3 },
  "alice@example.com": { id: "C001", name: "Alice Smith", email: "alice@example.com", tier: "premium", orders: 15 },
};

export function lookupCustomer(query: string): Customer | null {
  return CUSTOMERS[query] ?? null;
}

// ---------------------------------------------------------------------------
// Mock Knowledge Base
// ---------------------------------------------------------------------------

interface Article {
  id: string;
  title: string;
  content: string;
  category: string;
}

const ARTICLES: Article[] = [
  {
    id: "KB001",
    title: "How to Request a Refund",
    content: "To request a refund, go to Orders > Select Order > Request Refund. Refunds are processed within 5-7 business days.",
    category: "billing",
  },
  {
    id: "KB002",
    title: "Resetting Your Password",
    content: "Click 'Forgot Password' on the login page. Enter your email and follow the instructions in the reset email.",
    category: "account",
  },
  {
    id: "KB003",
    title: "Shipping Times and Tracking",
    content: "Standard shipping takes 5-7 business days. Express shipping takes 2-3 business days. Track your order in the Orders section.",
    category: "shipping",
  },
];

export function searchKnowledgeBase(query: string): Article[] {
  const lower = query.toLowerCase();
  const results = ARTICLES.filter(
    (a) =>
      a.title.toLowerCase().includes(lower) ||
      a.content.toLowerCase().includes(lower) ||
      a.category.includes(lower),
  );
  if (results.length > 0) return results;
  return [ARTICLES[Math.floor(Math.random() * ARTICLES.length)]];
}

// ---------------------------------------------------------------------------
// Mock Ticket System
// ---------------------------------------------------------------------------

let ticketCounter = 1000;

interface Ticket {
  ticketId: string;
  subject: string;
  description: string;
  priority: string;
  status: string;
  createdAt: string;
}

export function createTicket(subject: string, description: string, priority = "medium"): Ticket {
  ticketCounter += 1;
  return {
    ticketId: `TKT-${ticketCounter}`,
    subject,
    description,
    priority,
    status: "open",
    createdAt: new Date().toISOString(),
  };
}
