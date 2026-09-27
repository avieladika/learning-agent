import Foundation
import Combine
import AppKit
import Darwin

class ServerManager: ObservableObject {
    static let shared = ServerManager()

    @Published var isRunning: Bool = false
    @Published var isStarting: Bool = false
    @Published var outputLog: String = ""

    private var process: Process?
    private var outputPipe: Pipe?
    private var stopRequested = false

    // Hardcoded paths - Verify these match your system exactly!
    private let projectPath = "/Users/aviel/Documents/לימודים/פרוייקטים/learning agent"
    private let pythonPath = "/Users/aviel/Documents/לימודים/פרוייקטים/learning agent/.venv/bin/python3"

    func startServer() {
        guard !isRunning, !isStarting else { return }

        isStarting = true
        stopRequested = false
        outputLog = "Cleaning up an existing project server on port 8000...\n"
        terminateStaleProjectServers()

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            self.outputLog += "Starting a new server...\n"
            self.startNewServer()
        }
    }

    private func terminateStaleProjectServers() {
        let lsof = Process()
        let pipe = Pipe()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-n", "-P", "-t", "-iTCP:8000", "-sTCP:LISTEN"]
        lsof.standardOutput = pipe
        lsof.standardError = Pipe()

        do {
            try lsof.run()
            lsof.waitUntilExit()
        } catch {
            outputLog += "Could not inspect port 8000: \(error.localizedDescription)\n"
            return
        }

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        let pids = text.split(whereSeparator: \.isNewline).compactMap { Int32($0) }

        for pid in pids where processIsInProject(pid) {
            if Darwin.kill(pid, SIGTERM) == 0 {
                outputLog += "Stopped stale server process \(pid).\n"
            }
        }
    }

    private func processIsInProject(_ pid: Int32) -> Bool {
        let lsof = Process()
        let pipe = Pipe()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-a", "-p", String(pid), "-d", "cwd", "-Fn"]
        lsof.standardOutput = pipe
        lsof.standardError = Pipe()

        do {
            try lsof.run()
            lsof.waitUntilExit()
        } catch {
            return false
        }

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        return text.split(whereSeparator: \.isNewline).contains("n\(projectPath)")
    }

    private func updateStateFromServer(attemptsRemaining: Int = 10) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8000/docs")!)
        request.timeoutInterval = 0.5

        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            let reachable = (response as? HTTPURLResponse).map {
                (200..<500).contains($0.statusCode)
            } ?? false

            DispatchQueue.main.async {
                guard let self else { return }

                if reachable {
                    self.isStarting = false
                    self.isRunning = true
                    self.outputLog += "Server is ready at http://127.0.0.1:8000.\n"
                } else if attemptsRemaining > 1, self.isStarting {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                        self.updateStateFromServer(attemptsRemaining: attemptsRemaining - 1)
                    }
                } else {
                    self.isStarting = false
                    self.isRunning = false
                    self.outputLog += "Server did not become ready. Check the output above for details.\n"
                }
            }
        }.resume()
    }

    private func startNewServer() {

        // 1. Check if we have access (try to list contents)
        do {
            _ = try FileManager.default.contentsOfDirectory(atPath: projectPath)
            // If successful, launch
            launchProcess()
        } catch {
            isStarting = false
            outputLog += "No access to project directory. Requesting permission...\n"
            requestAccess()
        }
    }

    private func requestAccess() {
        DispatchQueue.main.async {
            let openPanel = NSOpenPanel()
            openPanel.message = "Please select the project folder to grant access"
            openPanel.prompt = "Grant Access"
            openPanel.canChooseFiles = false
            openPanel.canChooseDirectories = true
            openPanel.allowsMultipleSelection = false
            openPanel.directoryURL = URL(fileURLWithPath: self.projectPath)

            openPanel.begin { response in
                if response == .OK, let selectedURL = openPanel.url {
                    // Verify selected URL matches project path (or is parent)
                    if selectedURL.path == self.projectPath {
                        self.isStarting = true
                        // Create bookmark to persist access (optional, for now just use session access)
                        self.launchProcess()
                    } else {
                        self.outputLog += "Selected folder does not match project path.\n"
                    }
                } else {
                    self.isStarting = false
                    self.outputLog += "Permission denied by user.\n"
                }
            }
        }
    }

    private func launchProcess() {
        let task = Process()
        let pipe = Pipe()

        // Launch Python directly so Process owns uvicorn and can stop it reliably.
        task.executableURL = URL(fileURLWithPath: pythonPath)
        task.arguments = ["-m", "uvicorn", "backend.api.server:app", "--host", "127.0.0.1", "--port", "8000"]
        task.currentDirectoryURL = URL(fileURLWithPath: projectPath)

        // Set environment variables
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = projectPath
        // Ensure UTF-8 encoding for python output
        env["PYTHONIOENCODING"] = "utf-8"
        task.environment = env

        task.standardOutput = pipe
        task.standardError = pipe

        outputPipe = pipe
        process = task

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if let string = String(data: data, encoding: .utf8), !string.isEmpty {
                DispatchQueue.main.async {
                    self?.outputLog += string
                }
            }
        }

        do {
            try task.run()
            DispatchQueue.main.async {
                self.outputLog += "Server process launched. Waiting until it is ready...\n"
                self.updateStateFromServer()
            }
        } catch {
            DispatchQueue.main.async {
                self.isStarting = false
                self.outputLog += "Failed to launch shell process: \(error.localizedDescription)\n"
                self.isRunning = false
            }
        }

        task.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self else { return }
                if self.stopRequested {
                    self.isRunning = false
                    self.isStarting = false
                    self.outputLog += "\nServer process stopped.\n"
                    return
                }
                self.outputLog += "\nServer process terminated. Verifying server status...\n"
                self.updateStateFromServer(attemptsRemaining: 1)
            }
        }
    }

    func stopServer() {
        guard isRunning else { return }

        if let process {
            stopRequested = true
            process.terminate()
            outputLog += "Stopping server process...\n"
        } else {
            outputLog += "Server was started outside this app and was left running.\n"
        }

        self.process = nil
        self.outputPipe = nil
        self.isRunning = false
    }
}
