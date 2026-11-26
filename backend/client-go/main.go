package main

import (
	"client-go/connection"
	"log"
)

func main() {
	if err := connection.New().Run(); err != nil {
		log.Fatalf("Connection stopped; check configuration or identity: %v", err)
	}
}
