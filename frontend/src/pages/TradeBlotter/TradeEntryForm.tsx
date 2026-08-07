import { useState } from "react";

import { useAuth } from "../../auth/AuthContext";
import { useCreateBook, useCreateCounterparty } from "../../hooks/useReferenceData";
import { useSelection } from "../../hooks/useSelection";
import type { TradeCreate } from "../../hooks/useTrades";
import { useCreateTrade } from "../../hooks/useTrades";

interface Props {
  counterparties: { id: string; name: string }[];
  books: { id: string; name: string }[];
}

const inputClass =
  "bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-100 w-full";

const FLOATING_INDEX_BY_COMMODITY: Record<string, string> = {
  HENRY_HUB: "HENRY_HUB_PENULTIMATE",
  WTI: "WTI_CUSHING",
};

export function TradeEntryForm({ counterparties, books }: Props) {
  const { user } = useAuth();
  const { commodity } = useSelection();
  const createTrade = useCreateTrade();
  const createCounterparty = useCreateCounterparty();
  const createBook = useCreateBook();

  const [form, setForm] = useState({
    tradeDate: new Date().toISOString().slice(0, 10),
    counterpartyId: "",
    bookId: "",
    tradeType: "SWAP" as TradeCreate["trade_type"],
    buySell: "BUY" as TradeCreate["buy_sell"],
    volume: "10000",
    fixedPrice: "3.00",
    deliveryStartMonth: "",
    deliveryEndMonth: "",
    optionType: "CALL" as NonNullable<TradeCreate["option_type"]>,
    strikePrice: "3.00",
    premium: "0.20",
    optionVolatility: "0.35",
  });
  const [newCounterpartyName, setNewCounterpartyName] = useState("");
  const [newBookName, setNewBookName] = useState("");

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const isOption = form.tradeType === "OPTION";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.counterpartyId || !form.bookId || !form.deliveryStartMonth || !form.deliveryEndMonth) {
      return;
    }
    await createTrade.mutateAsync({
      trade_date: form.tradeDate,
      counterparty_id: form.counterpartyId,
      book_id: form.bookId,
      commodity,
      trade_type: form.tradeType,
      buy_sell: form.buySell,
      volume: Number(form.volume),
      volume_unit: commodity === "WTI" ? "BBL" : "MMBTU",
      price_currency: "USD",
      floating_index: FLOATING_INDEX_BY_COMMODITY[commodity] ?? "HENRY_HUB_PENULTIMATE",
      delivery_start_month: form.deliveryStartMonth,
      delivery_end_month: form.deliveryEndMonth,
      // OPTION is priced off strike/premium/vol, not fixed_price -- the backend
      // rejects whichever set doesn't match trade_type, so only send one.
      ...(isOption
        ? {
            fixed_price: null,
            option_type: form.optionType,
            strike_price: Number(form.strikePrice),
            premium: Number(form.premium),
            option_volatility: Number(form.optionVolatility),
          }
        : { fixed_price: Number(form.fixedPrice) }),
    });
  }

  if (user?.role !== "TRADER" && user?.role !== "ADMIN") {
    return (
      <p className="text-sm text-slate-500 bg-slate-900/50 border border-slate-800 rounded-lg p-4">
        Your role ({user?.role}) can view trades but not book new ones.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      <form onSubmit={handleSubmit} className="md:col-span-2 grid grid-cols-2 gap-3 bg-slate-900/50 p-4 rounded-lg border border-slate-800">
        <label className="col-span-2 text-xs uppercase tracking-wide text-slate-500">
          New {commodity === "WTI" ? "WTI" : "Henry Hub"} trade
        </label>

        <div>
          <label className="text-xs text-slate-400">Trade date</label>
          <input type="date" className={inputClass} value={form.tradeDate} onChange={(e) => update("tradeDate", e.target.value)} required />
        </div>
        <div>
          <label className="text-xs text-slate-400">Counterparty</label>
          <select className={inputClass} value={form.counterpartyId} onChange={(e) => update("counterpartyId", e.target.value)} required>
            <option value="">Select…</option>
            {counterparties.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Book</label>
          <select className={inputClass} value={form.bookId} onChange={(e) => update("bookId", e.target.value)} required>
            <option value="">Select…</option>
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Type</label>
          <select className={inputClass} value={form.tradeType} onChange={(e) => update("tradeType", e.target.value as TradeCreate["trade_type"])}>
            <option value="SWAP">Swap</option>
            <option value="FORWARD">Forward</option>
            <option value="OPTION">Option</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Buy / Sell</label>
          <select className={inputClass} value={form.buySell} onChange={(e) => update("buySell", e.target.value as TradeCreate["buy_sell"])}>
            <option value="BUY">Buy</option>
            <option value="SELL">Sell</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400">Volume ({commodity === "WTI" ? "bbl" : "MMBtu"})</label>
          <input className={inputClass} value={form.volume} onChange={(e) => update("volume", e.target.value)} required />
        </div>
        {!isOption && (
          <div>
            <label className="text-xs text-slate-400">
              Fixed price (${commodity === "WTI" ? "/bbl" : "/MMBtu"})
            </label>
            <input className={inputClass} value={form.fixedPrice} onChange={(e) => update("fixedPrice", e.target.value)} required />
          </div>
        )}
        <div>
          <label className="text-xs text-slate-400">Delivery start month (= option expiry, for OPTION)</label>
          <input type="date" className={inputClass} value={form.deliveryStartMonth} onChange={(e) => update("deliveryStartMonth", e.target.value)} required />
        </div>
        <div>
          <label className="text-xs text-slate-400">Delivery end month</label>
          <input type="date" className={inputClass} value={form.deliveryEndMonth} onChange={(e) => update("deliveryEndMonth", e.target.value)} required />
        </div>
        {isOption && (
          <>
            <div>
              <label className="text-xs text-slate-400">Call / Put</label>
              <select
                className={inputClass}
                value={form.optionType}
                onChange={(e) => update("optionType", e.target.value as typeof form.optionType)}
              >
                <option value="CALL">Call</option>
                <option value="PUT">Put</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400">Strike price</label>
              <input className={inputClass} value={form.strikePrice} onChange={(e) => update("strikePrice", e.target.value)} required />
            </div>
            <div>
              <label className="text-xs text-slate-400">Premium (per unit)</label>
              <input className={inputClass} value={form.premium} onChange={(e) => update("premium", e.target.value)} required />
            </div>
            <div>
              <label className="text-xs text-slate-400">Volatility (flat, annualized)</label>
              <input className={inputClass} value={form.optionVolatility} onChange={(e) => update("optionVolatility", e.target.value)} required />
            </div>
          </>
        )}

        <div className="col-span-2 flex items-center gap-3 mt-1">
          <button
            type="submit"
            disabled={createTrade.isPending}
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-1.5 rounded-md disabled:opacity-50"
          >
            {createTrade.isPending ? "Booking…" : "Book trade"}
          </button>
          {createTrade.isError && <span className="text-sm text-red-400">Failed to book trade.</span>}
          {createTrade.isSuccess && <span className="text-sm text-emerald-400">Trade booked.</span>}
        </div>
      </form>

      <div className="space-y-4">
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-800">
          <label className="text-xs uppercase tracking-wide text-slate-500">Add counterparty</label>
          <div className="mt-2 flex gap-2">
            <input className={inputClass} value={newCounterpartyName} onChange={(e) => setNewCounterpartyName(e.target.value)} placeholder="Name" />
            <button
              type="button"
              className="bg-slate-700 hover:bg-slate-600 text-sm px-3 rounded-md"
              onClick={() => {
                if (newCounterpartyName.trim()) {
                  createCounterparty.mutate(newCounterpartyName.trim());
                  setNewCounterpartyName("");
                }
              }}
            >
              Add
            </button>
          </div>
        </div>
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-800">
          <label className="text-xs uppercase tracking-wide text-slate-500">Add book</label>
          <div className="mt-2 flex gap-2">
            <input className={inputClass} value={newBookName} onChange={(e) => setNewBookName(e.target.value)} placeholder="Name" />
            <button
              type="button"
              className="bg-slate-700 hover:bg-slate-600 text-sm px-3 rounded-md"
              onClick={() => {
                if (newBookName.trim()) {
                  createBook.mutate(newBookName.trim());
                  setNewBookName("");
                }
              }}
            >
              Add
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
