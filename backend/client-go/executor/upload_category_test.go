package executor

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"client-go/config"
)

func TestSavedUploadCategoryIsCanonicalAndCommandSourceRecorded(t *testing.T) {
	filePath := filepath.Join(t.TempDir(), "capture.png")
	if err := os.WriteFile(filePath, []byte("image"), 0600); err != nil {
		t.Fatal(err)
	}
	var gotCategory, gotExtra string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := r.ParseMultipartForm(4096); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		gotCategory = r.FormValue("category")
		gotExtra = r.FormValue("extra")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":0,"data":{"artifact_id":"saved-1"}}`))
	}))
	defer server.Close()
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = server.URL
	defer func() { config.UPLOAD_BASE_URL = old }()
	session := &Session{ClientID: "client1", HostName: "host"}
	if _, err := session.uploadFileToServer(filePath, "screenshots"); err != nil {
		t.Fatal(err)
	}
	if gotCategory != "screenshots" || gotExtra != `{"saved_from":"client_command","source_command":"screenshot"}` {
		t.Fatalf("wrong screenshot classification %q extra %q", gotCategory, gotExtra)
	}
	if _, err := session.uploadFileToServer(filePath, ""); err != nil {
		t.Fatal(err)
	}
	if gotCategory != "inbox" || gotExtra != "" {
		t.Fatalf("wrong default classification %q extra %q", gotCategory, gotExtra)
	}
}
