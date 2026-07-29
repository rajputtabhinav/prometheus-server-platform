import React from "react";
import ReactDOM from "react-dom/client";
import { SWRConfig } from "swr";

import { App } from "./App";
import "./index.css";
import { NonRetryableRequestError, jsonFetcher } from "./lib/fetcher";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SWRConfig
      value={{
        fetcher: jsonFetcher,
        revalidateOnFocus: false,
        dedupingInterval: 4000,
        onErrorRetry: (error, _key, _config, revalidate, context) => {
          if (error instanceof NonRetryableRequestError) {
            return;
          }
          if (context.retryCount >= 2) {
            return;
          }
          window.setTimeout(() => {
            void revalidate({ retryCount: context.retryCount + 1 });
          }, 1500 * (context.retryCount + 1));
        }
      }}
    >
      <App />
    </SWRConfig>
  </React.StrictMode>
);
