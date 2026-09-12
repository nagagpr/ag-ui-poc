import React, { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";

const API = "/api";

ModuleRegistry.registerModules([AllCommunityModule]);

const customerColumns = [
  { field: "id", headerName: "Customer ID", width: 120 },
  { field: "name", headerName: "Customer", flex: 1.3 },
  { field: "email", headerName: "Email", flex: 1.7 },
  { field: "status", headerName: "Status", width: 110 },
  { field: "risk", headerName: "Risk", width: 100 },
  {
    field: "balance",
    headerName: "Balance",
    width: 130,
    valueFormatter: p => `$${Number(p.value).toLocaleString()}`
  },
  { field: "city", headerName: "City", width: 130 }
];

const transactionColumns = [
  { field: "id", headerName: "Transaction", width: 125 },
  { field: "customer_id", headerName: "Customer ID", width: 120 },
  { field: "type", headerName: "Type", width: 120 },
  {
    field: "amount",
    headerName: "Amount",
    width: 120,
    valueFormatter: p => `$${Number(p.value).toLocaleString()}`
  },
  { field: "status", headerName: "Status", width: 120 },
  { field: "date", headerName: "Date", width: 120 }
];

const examples = [
  "Show all active customers",
  "Show high risk customers",
  "Show customers with balance greater than 10000",
  "Show pending transactions",
  "Show transactions for customer 1003",
  "Give me details for customer 1005",
  "What is the total balance?"
];

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("ag-ui-theme") || "dark");
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Hello! I am the local AG-UI POC agent. Ask me about the dummy customers or transactions."
    }
  ]);
  const [rows, setRows] = useState([]);
  const [gridType, setGridType] = useState("customers");
  const [loading, setLoading] = useState(false);

  const columns = useMemo(
    () => gridType === "transactions" ? transactionColumns : customerColumns,
    [gridType]
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("ag-ui-theme", theme);
  }, [theme]);

  useEffect(() => {
    async function loadCustomers() {
      try {
        const response = await fetch(`${API}/customers`);
        if (!response.ok) throw new Error("Could not load customers");
        setRows(await response.json());
      } catch (err) {
        setMessages(prev => [...prev, { role: "assistant", text: `Error: ${err.message}` }]);
      }
    }

    loadCustomers();
  }, []);

  async function sendPrompt(value = prompt) {
    const text = value.trim();
    if (!text || loading) return;

    setMessages(prev => [...prev, { role: "user", text }]);
    setPrompt("");
    setLoading(true);

    try {
      const response = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text })
      });

      if (!response.ok) throw new Error("Backend request failed");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantText = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";

        for (const raw of events) {
          const lines = raw.split("\n");
          const eventName = lines.find(l => l.startsWith("event:"))?.slice(6).trim();
          const dataLine = lines.find(l => l.startsWith("data:"));
          if (!dataLine) continue;

          const data = JSON.parse(dataLine.slice(5).trim());

          if (eventName === "TEXT_MESSAGE_CONTENT") {
            assistantText += data.delta || "";
          }

          if (eventName === "CUSTOM_DATA" && data.type === "grid_data") {
            setGridType(data.grid);
            setRows(data.rows || []);
          }
        }
      }

      setMessages(prev => [...prev, { role: "assistant", text: assistantText || "No response." }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: "assistant", text: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>AG-UI Local Data POC</h1>
          <p>Natural-language prompts → FastAPI → dummy data → AG Grid</p>
        </div>
        <div className="header-actions">
          <div className="theme-switcher" role="group" aria-label="Theme">
            <button
              className={theme === "dark" ? "active" : ""}
              onClick={() => setTheme("dark")}
              aria-pressed={theme === "dark"}
            >
              Dark
            </button>
            <button
              className={theme === "light" ? "active" : ""}
              onClick={() => setTheme("light")}
              aria-pressed={theme === "light"}
            >
              Light
            </button>
          </div>
          <span className="badge">AWS NOT REQUIRED</span>
        </div>
      </header>

      <main>
        <section className="chat-panel">
          <h2>Chat</h2>

          <div className="messages">
            {messages.map((m, i) => (
              <div key={i} className={`message ${m.role}`}>
                <div className="role">{m.role === "user" ? "You" : "AG-UI Agent"}</div>
                <div>{m.text}</div>
              </div>
            ))}
            {loading && <div className="typing">Agent is processing the prompt…</div>}
          </div>

          <div className="examples">
            <div className="label">Try a prompt</div>
            {examples.map(e => (
              <button key={e} onClick={() => sendPrompt(e)}>{e}</button>
            ))}
          </div>

          <div className="composer">
            <input
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              onKeyDown={e => e.key === "Enter" && sendPrompt()}
              placeholder="Ask something about customers or transactions..."
            />
            <button className="send" onClick={() => sendPrompt()} disabled={loading}>
              {loading ? "..." : "Send"}
            </button>
          </div>
        </section>

        <section className="grid-panel">
          <div className="grid-title">
            <div>
              <h2>{gridType === "transactions" ? "Transactions" : "Customers"}</h2>
              <span>{rows.length} rows returned by the last prompt</span>
            </div>
            <button onClick={() => setRows([])}>Clear</button>
          </div>

          <div className={`ag-theme-quartz${theme === "dark" ? "-dark" : ""} grid`}>
            <AgGridReact
              rowData={rows}
              columnDefs={columns}
              pagination={true}
              paginationPageSize={10}
              animateRows={true}
              defaultColDef={{
                sortable: true,
                filter: true,
                resizable: true
              }}
            />
          </div>
        </section>
      </main>

      <footer>
        Local deterministic prompt router • FastAPI • SSE • AG Grid • React
      </footer>
    </div>
  );
}
