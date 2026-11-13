package executor

import "context"

// Local filesystem writers share one guard across sessions and inbound transfers.
var filesystemMutation = make(chan struct{}, 1)

func acquireFilesystemMutation(ctx context.Context) (func(), error) {
	select {
	case filesystemMutation <- struct{}{}:
		if err := ctx.Err(); err != nil {
			<-filesystemMutation
			return nil, err
		}
		return func() { <-filesystemMutation }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}
