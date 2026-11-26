package executor

import (
	"client-go/config"
	"context"
)

// Transfer selection is runtime configuration; transfer control messages stay unchanged.
type fileTransferStrategy interface {
	mode() string
	upload(*Session, context.Context, string, string, string, string, string) error
	download(*Session, context.Context, string, map[string]interface{}) error
}

type httpStreamingTransfer struct{}

func (httpStreamingTransfer) mode() string { return config.TransferHTTPStreaming }
func (httpStreamingTransfer) upload(s *Session, ctx context.Context, id, path, filename, typ, category string) error {
	return s.uploadTransferFile(ctx, id, path, filename, typ, category)
}
func (httpStreamingTransfer) download(s *Session, ctx context.Context, id string, p map[string]interface{}) error {
	return s.downloadTransferFile(ctx, id, p)
}

type tcpStreamingTransfer struct{}

func (tcpStreamingTransfer) mode() string { return config.TransferTCPStreaming }
func (tcpStreamingTransfer) upload(s *Session, ctx context.Context, id, path, filename, typ, category string) error {
	return s.uploadTransferFileTCP(ctx, id, path, filename, typ, category)
}
func (tcpStreamingTransfer) download(s *Session, ctx context.Context, id string, p map[string]interface{}) error {
	return s.downloadTransferFileTCP(ctx, id, p)
}

func transferStrategyForMode(mode string) fileTransferStrategy {
	if mode == config.TransferTCPStreaming {
		return tcpStreamingTransfer{}
	}
	return httpStreamingTransfer{}
}

func currentTransferStrategy() fileTransferStrategy {
	return transferStrategyForMode(config.Runtime().FileTransferMode())
}
