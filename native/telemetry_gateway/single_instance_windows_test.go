//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"testing"
)

func TestBridgeSingleInstance(t *testing.T) {
	if name := os.Getenv("BOMANA_TEST_INSTANCE"); name != "" {
		release, acquired, err := claimNamedInstance(name)
		if err != nil || !acquired {
			t.Fatalf("child claim: acquired=%v err=%v", acquired, err)
		}
		defer release()
		fmt.Println("claimed")
		_, _ = bufio.NewReader(os.Stdin).ReadByte()
		return
	}
	name := fmt.Sprintf(`Local\BomanaBridge-test-%d`, os.Getpid())
	child := exec.Command(os.Args[0], "-test.run=^TestBridgeSingleInstance$")
	child.Env = append(os.Environ(), "BOMANA_TEST_INSTANCE="+name)
	stdin, _ := child.StdinPipe()
	defer stdin.Close()
	stdout, _ := child.StdoutPipe()
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = child.Process.Kill(); _ = child.Wait() })
	if line, err := bufio.NewReader(stdout).ReadString('\n'); err != nil || line != "claimed\n" {
		t.Fatalf("child startup: %q %v", line, err)
	}
	if release, acquired, err := claimNamedInstance(name); err != nil || acquired {
		if release != nil {
			release()
		}
		t.Fatalf("duplicate process allowed: acquired=%v err=%v", acquired, err)
	}
	_ = child.Process.Kill()
	_ = child.Wait()
	release, acquired, err := claimNamedInstance(name)
	if err != nil || !acquired {
		t.Fatalf("restart after crash: acquired=%v err=%v", acquired, err)
	}
	release()
}
