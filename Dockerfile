# Use the official Golang image to build the Go app
FROM golang:1.17-alpine AS builder

WORKDIR /app

# Copy go mod and sum files
COPY go.mod go.sum ./

# Download all dependencies. Dependencies will be cached if the go.mod and go.sum files are not changed
RUN go mod download

# Copy the source from the current directory to the working Directory inside the container
COPY . .

# Build the Go app
RUN CGO_ENABLED=0 GOOS=linux go build -o main .

# Start fresh from a smaller image
FROM alpine:latest

# Install Python for running scripts
RUN apk --no-cache add python3

# Copy the Pre-built binary file from the previous stage
WORKDIR /root/
COPY --from=builder /app/main .

# Copy certificates and scripts
COPY certs /root/certs
COPY scripts /root/scripts
COPY templates /root/templates

# Expose ports
EXPOSE 8080 8443

# Command to run the executable
CMD ["./main"]