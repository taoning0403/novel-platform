import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.ts",
    server: {
      deps: {
        inline: ["antd", "@ant-design/icons", "@ant-design/colors"],
      },
    },
  },
});
