package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
)

func main() {
	defaultPort := 2323
	if env := os.Getenv("PORT"); env != "" {
		if p, err := strconv.Atoi(env); err == nil {
			defaultPort = p
		}
	}

	port := flag.Int("port", defaultPort, "TCP port to listen on (also reads PORT env var)")
	addr := flag.String("addr", "0.0.0.0", "interface address to bind")
	htmlDir := flag.String("html", "html", "directory containing static html assets")
	flag.Parse()

	abs, err := filepath.Abs(*htmlDir)
	if err != nil {
		log.Fatalf("resolve html dir: %v", err)
	}
	if _, err := os.Stat(abs); err != nil {
		log.Fatalf("html dir %q not accessible: %v", abs, err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/convert", handleConvert)
	mux.Handle("/", http.FileServer(http.Dir(abs)))

	listenAddr := fmt.Sprintf("%s:%d", *addr, *port)
	log.Printf("swaggertopy listening on %s, serving %s", listenAddr, abs)
	if err := http.ListenAndServe(listenAddr, mux); err != nil {
		log.Fatal(err)
	}
}

func handleConvert(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}
	defer r.Body.Close()
	body, err := io.ReadAll(io.LimitReader(r.Body, 32<<20)) // 32 MiB cap
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	eval, err := newMyEval(string(body))
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{
		"code":  eval.GenClass,
		"title": eval.Title,
	})
}
