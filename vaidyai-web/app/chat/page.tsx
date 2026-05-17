"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Mic, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { quickPrompts } from "@/lib/data";

type ChatMessage = {
  role: "user" | "ai";
  text: string;
  timestamp: string;
  meta?: string;
};

type WebhookResponse = {
  response: string;
  intent: string;
  state: string;
};

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [jwtToken, setJwtToken] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [status, setStatus] = useState("Connecting...");

  const userId = useMemo(() => {
    if (typeof window === "undefined") return "frontend_user";
    const existing = localStorage.getItem("vaidyai_user_id");
    if (existing) return existing;
    const created = `frontend_${crypto.randomUUID()}`;
    localStorage.setItem("vaidyai_user_id", created);
    return created;
  }, []);

  const now = () => new Date().toLocaleTimeString();

  const append = (message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  };

  const authenticate = async (): Promise<string> => {
    const body = new URLSearchParams();
    body.append("username", "admin");
    body.append("password", "password");

    const res = await fetch(`${BACKEND_URL}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString()
    });

    if (!res.ok) {
      throw new Error("Authentication failed");
    }

    const data = await res.json();
    const token = data.access_token as string;
    setJwtToken(token);
    return token;
  };

  const callWebhook = async (token: string, message: string): Promise<WebhookResponse> => {
    const res = await fetch(`${BACKEND_URL}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ user_id: userId, message })
    });

    if (res.status === 401) {
      const freshToken = await authenticate();
      return callWebhook(freshToken, message);
    }

    if (!res.ok) {
      throw new Error(`Webhook failed (${res.status})`);
    }

    return res.json();
  };

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      try {
        await authenticate();
        if (!mounted) return;
        setStatus(`Connected to ${BACKEND_URL}`);
        setMessages([
          {
            role: "ai",
            text: "Hello, I am Vaidya AI. How can I help you today?",
            timestamp: now()
          }
        ]);
      } catch {
        if (!mounted) return;
        setStatus(`Backend not reachable at ${BACKEND_URL}`);
        setMessages([
          {
            role: "ai",
            text: "I cannot reach the backend right now. Please check the deployed backend URL and refresh.",
            timestamp: now()
          }
        ]);
      }
    };

    init();
    return () => {
      mounted = false;
    };
  }, []);

  const send = async () => {
    const value = text.trim();
    if (!value || isSending) return;

    append({ role: "user", text: value, timestamp: now() });
    setText("");
    setIsSending(true);

    try {
      const token = jwtToken ?? (await authenticate());
      const data = await callWebhook(token, value);
      append({
        role: "ai",
        text: data.response,
        timestamp: now(),
        meta: `intent: ${data.intent} · state: ${data.state}`
      });
    } catch {
      append({
        role: "ai",
        text: "Something went wrong while contacting backend. Please try again.",
        timestamp: now()
      });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-6 lg:px-8">
      <div className="glass mb-4 flex items-center justify-between p-4">
        <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-cyan-300" /><p className="font-medium">Vaidya AI Receptionist</p></div>
        <p className="text-xs text-slate-400">{status}</p>
      </div>

      <section className="glass flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m, i) => (
          <motion.div key={`${m.timestamp}-${i}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={m.role === "user" ? "ml-auto max-w-[80%] rounded-2xl bg-cyan/20 p-3" : "max-w-[80%] rounded-2xl bg-white/10 p-3"}>
            <p className="text-sm">{m.text}</p>
            {m.meta ? <p className="mt-1 text-[10px] text-cyan-200">{m.meta}</p> : null}
            <p className="mt-1 text-[10px] text-slate-400">{m.timestamp}</p>
          </motion.div>
        ))}
        {isSending ? <div className="max-w-[80%] rounded-2xl bg-white/10 p-3 text-xs text-slate-400">Vaidya AI is typing...</div> : null}
      </section>

      <div className="mt-3 flex flex-wrap gap-2">
        {quickPrompts.map((prompt) => (
          <button key={prompt} onClick={() => setText(prompt)} className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-slate-300 hover:bg-white/10">{prompt}</button>
        ))}
      </div>

      <footer className="mt-3 flex items-center gap-2">
        <Button variant="outline" size="sm"><Mic className="h-4 w-4" /></Button>
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void send();
            }
          }}
          placeholder="Describe symptoms or ask to book appointment..."
        />
        <Button onClick={() => void send()} disabled={isSending}><Send className="h-4 w-4" /></Button>
      </footer>
    </main>
  );
}
